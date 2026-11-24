# Vektor Architecture

This page explains how Vektor is put together, for developers who are new to the codebase. It is based on the code as of **2026-11-24**. Diagrams are [Mermaid](https://mermaid.js.org/) and render on GitHub, GitLab, and in VS Code with a Mermaid preview extension.

> **Reading guide.** Some modules exist and are exposed through their own endpoints but are **not yet on the chat path**. They are marked with a status in [section 11](#11-what-is-wired-in-and-what-is-not). Do not assume a feature is enforced just because its module exists.

**Contents**

1. [System context](#1-system-context)
2. [Backend layers](#2-backend-layers)
3. [Module map](#3-module-map)
4. [A chat turn, end to end](#4-a-chat-turn-end-to-end)
5. [Knowledge and RAG](#5-knowledge-and-rag)
6. [Identity, tenancy, and access](#6-identity-tenancy-and-access)
7. [Data model](#7-data-model)
8. [Workflows](#8-workflows)
9. [Frontend](#9-frontend)
10. [Deployment](#10-deployment)
11. [What is wired in and what is not](#11-what-is-wired-in-and-what-is-not)
12. [Where to look in the code](#12-where-to-look-in-the-code)

---

## 1. System context

Vektor is a FastAPI backend plus a Next.js web app. People use the web app. Chat tools and automations can also reach the backend directly. The backend talks to an OpenAI-compatible LLM provider and stores everything in SQL.

```mermaid
flowchart LR
    user(["Person using the web app"])
    chatops(["Chat channels<br/>Telegram, Slack, Discord"])
    admin(["Tenant admin / operator"])

    subgraph vektor["Vektor"]
        ui["Web app<br/>Next.js 16 + React 19"]
        proxy["Same-origin proxy<br/>/api/backend/*"]
        api["Backend API<br/>FastAPI"]
        db[("SQL database<br/>SQLite (dev)<br/>PostgreSQL + pgvector (prod)")]
        skills[["Skills folder<br/>SKILL.md files"]]
    end

    llm["LLM provider<br/>OpenAI-compatible<br/>(OpenRouter by default)"]
    embed["Embedding provider<br/>OpenAI-compatible or Voyage"]
    rerank["Reranker (optional)<br/>Voyage API or local BGE"]
    langfuse["Langfuse tracing (optional)"]
    sandbox["Command sandbox (optional)<br/>Docker or SSH host"]

    user --> ui --> proxy --> api
    chatops -- "POST /api/v1/gateway/webhook" --> api
    admin -- "admin endpoints, CLI" --> api
    api --> db
    api --> skills
    api --> llm
    api --> embed
    api -.-> rerank
    api -.-> langfuse
    api -.-> sandbox
```

Solid arrows are always used. Dashed arrows are optional and turned on through settings.

---

## 2. Backend layers

Code lives under `src/`. Requests move top to bottom. Each layer only calls the layer below it.

```mermaid
flowchart TB
    subgraph edge["HTTP edge: src/api"]
        mw["Middleware<br/>request id, API-key auth,<br/>per-user rate limit, usage flush"]
        routers["Routers<br/>chat, conversations, knowledge, usage, admin,<br/>me, providers, keys, workflows, mcp, gateway"]
        deps["Dependencies<br/>principal, DB session,<br/>usage recorder, budget check,<br/>service factory"]
    end

    subgraph runtime["Runtime: src/modules/ai_runtime"]
        chat["ChatService<br/>turn orchestration"]
        retr["KnowledgeRetriever<br/>+ reranker"]
        ground["Grounding checks<br/>+ reply envelope"]
    end

    subgraph domain["Domain modules: src/modules"]
        know["knowledge"]
        conv["conversations"]
        ident["identity"]
        usage["usage<br/>metering, budget, tracing"]
        tools["tools<br/>registry + built-ins"]
        wf["workflows"]
        prov["settings + providers"]
        gw["llm_gateway + billing"]
        other["skills, mcp_apps, sandbox"]
    end

    subgraph adapters["Adapters"]
        mg["model_gateway<br/>chat + embeddings clients"]
    end

    subgraph store["Storage: src/core"]
        orm[("SQLAlchemy async<br/>SQLite / PostgreSQL")]
    end

    mw --> routers
    routers --> deps
    deps --> chat
    routers --> wf
    chat --> retr
    chat --> ground
    chat --> tools
    retr --> know
    chat --> conv
    chat --> usage
    know --> mg
    chat --> mg
    deps --> ident
    deps --> prov
    routers --> gw
    know --> orm
    conv --> orm
    ident --> orm
    usage --> orm
    wf --> orm
    prov --> orm
    gw --> orm
```

**Conventions that hold across the backend**

- A module usually has `models.py` (tables), `repository.py` (queries), and `schemas.py` (Pydantic types).
- **Repositories receive the caller's `Principal`** and add tenant and owner filters themselves. Routers should never build such filters by hand.
- Routers stay thin: validate input, call a repository or service, map errors to HTTP codes.
- All settings are environment variables prefixed `VEKTOR_`, validated in `src/core/config/settings.py`.

---

## 3. Module map

| Module (`src/modules/…`) | Responsibility |
|---|---|
| `ai_runtime` | `ChatService` (one chat turn), retrieval, reranking, grounding verification, reply envelope, system prompt |
| `knowledge` | Document ingestion (extract, chunk, embed), hybrid search, per-document visibility and grants |
| `conversations` | Conversations and messages, history token budgeting, compaction into a summary |
| `identity` | `Principal` (user, tenant, roles), API keys (stored hashed), audit log |
| `model_gateway` | OpenAI-compatible chat client (streaming, tool-call fragments), embeddings clients |
| `usage` | Metering of every model call, tenant monthly token budget, tool usage and feedback, optional Langfuse tracing |
| `tools` | Tool registry with a risk gate, built-in tools, result cache |
| `workflows` | Multi-step workflows with human approval checkpoints |
| `settings`, `providers` | Per-user provider selection and profiles, model discovery |
| `llm_gateway` | Bring-your-own-key vault (envelope encryption), tenant key policy, SSRF guard, model registry |
| `billing` | Credit ledger with reserve, settle, and release holds |
| `skills` | `SKILL.md` discovery and a catalogue injected into the prompt |
| `mcp_apps` | Registry of interactive HTML widgets (`ui://` resources) |
| `sandbox` | Isolated command execution backends (disabled, Docker, SSH) |

---

## 4. A chat turn, end to end

This is the streaming path, `POST /api/v1/chat/stream`. The non-streaming `POST /api/v1/chat` runs the same steps and returns one JSON body.

```mermaid
sequenceDiagram
    autonumber
    actor U as Person
    participant B as Browser
    participant P as Next.js proxy
    participant A as FastAPI
    participant C as ChatService
    participant R as Retriever
    participant D as Database
    participant L as LLM provider
    participant T as Tools

    U->>B: Send message
    B->>P: POST /api/backend/chat/stream
    P->>A: POST /api/v1/chat/stream with X-API-Key
    A->>D: Look up API key hash, build Principal
    A->>A: Rate limit per tenant and user
    A->>A: Budget check, reject with 429 if exhausted
    A->>C: stream_turn
    C->>D: Load conversation, scoped to Principal
    C-->>B: event meta
    C-->>B: event status "Searching knowledge base"
    C->>R: retrieve
    R->>D: Hybrid search over documents the caller may read
    opt Low score or a short follow-up
        R->>L: Rewrite the query, usually a cheaper model
    end
    R-->>C: Ranked chunks plus a confidence grade
    alt Grounding gate refuses to answer
        C-->>B: event delta with the refusal text
    else Answer normally
        C-->>B: event citations
        loop Up to N tool rounds, then one final round without tools
            C->>L: Stream request with history, context, tool schemas
            L-->>C: Text pieces and tool-call fragments
            C-->>B: event delta for each text piece
            opt Model asked for a tool
                C-->>B: event status "Running tool"
                C->>T: Execute through allowlist and risk gate
                T-->>C: Output, wrapped as untrusted data
                C-->>B: event tool
            end
        end
        C->>C: Verify citations, commands, hostnames against context
        C->>D: Save user and assistant messages
        C-->>B: event done with usage and grounding
    end
    A->>D: Flush usage events after the response
    B->>U: Rendered answer with sources
```

**Things worth knowing**

- **Events** sent to the browser: `meta`, `status`, `citations`, `tool`, `reasoning`, `delta`, `done`, `error`. Their shape is `ChatStreamEvent` in `src/modules/ai_runtime/schemas.py`.
- **Stop button.** If the browser disconnects mid-answer, `src/api/streaming.py` saves the text already sent with a `(Stopped)` marker. If no text was sent yet, nothing is saved.
- **Errors during streaming** become an `error` event, not a broken HTTP response, because the `200` status is already sent.
- **Usage events** are collected in memory during the request and written after the response, so metering never blocks or breaks a chat.
- **Tool output is untrusted.** It is fenced in `<tool_output>` tags and capped, so text inside a tool result cannot act as an instruction.

---

## 5. Knowledge and RAG

### 5.1 Ingestion

```mermaid
flowchart LR
    up["Upload or paste<br/>POST /knowledge/documents<br/>or /knowledge/documents/upload"] --> size{"Size at most 15 MB?"}
    size -- "no" --> rej["413 Too large"]
    size -- "yes" --> ext["Extract text<br/>txt, md, csv, json, pdf, docx, images"]
    ext --> chunk["Chunk<br/>heading-aware, overlapping"]
    chunk --> dup{"Same content already<br/>in this tenant?"}
    dup -- "yes" --> conflict["409 Duplicate"]
    dup -- "no" --> emb["Embed in batches of 64"]
    emb --> save[("knowledge_documents<br/>knowledge_chunks")]
    ext -. "image" .-> vision["Vision model<br/>reads text from the image"]
    vision --> chunk
    save --> pg["PostgreSQL only:<br/>pgvector + full-text columns"]
```

- Files are read in 1 MB pieces and rejected as soon as they pass the limit. PDFs over 500 pages are refused. PDF and DOCX parsing runs off the event loop.
- Every document records its **owner, tenant, and visibility** (`private`, `tenant`, or `shared` with grants). See [section 6](#6-identity-tenancy-and-access).
- Embedding and vision calls are metered like chat calls.

### 5.2 Retrieval

```mermaid
flowchart TB
    q["User message"] --> mode{"Retrieval mode"}
    mode -- "off" --> none["No search"]
    mode -- "explicit or always" --> direct["Hybrid search<br/>(always mode also splits<br/>compound questions)"]
    mode -- "auto" --> chit{"Small talk?"}
    chit -- "yes" --> none
    chit -- "no" --> split["Split compound questions<br/>into up to 2 sub-queries"]
    split --> s1["Stage 1: hybrid search<br/>semantic + lexical, only documents<br/>the caller is allowed to read"]
    s1 --> need{"Top score low, or short<br/>follow-up question?"}
    need -- "no" --> s2
    need -- "yes" --> rw["Rewrite query with a small LLM<br/>using recent history"]
    rw --> s1b["Search again"]
    s1b --> s2
    direct --> s2["Stage 2: rerank<br/>heuristic, Voyage, or local BGE"]
    s2 --> parent["Expand to parent section<br/>(not implemented, see section 11)"]
    parent --> prune["Prune and merge<br/>drop weak chunks, cap token budget"]
    prune --> grade{"Confidence"}
    grade -- "high" --> ctx["Inject excerpts"]
    grade -- "low" --> ctxl["Inject excerpts plus a note<br/>to ask for clarification"]
    grade -- "empty" --> gate["Tell the model nothing was found,<br/>do not invent procedures"]
```

- **SQLite** (development) computes cosine similarity in Python over embeddings stored as JSON. This is fine for small knowledge bases and slow for large ones.
- **PostgreSQL** (production) uses `pgvector` and full-text search in SQL (migration `0006`).
- Only chunks embedded with the **currently configured embedding model** are compared.
- The reranker is chosen by settings: a zero-latency heuristic, the Voyage rerank API, or a local cross-encoder.
- Each excerpt carries a freshness note when its document has not been updated for `retrieval_stale_days`.

---

## 6. Identity, tenancy, and access

Every request is resolved to a `Principal` (user id, tenant id, roles) by the auth middleware. Repositories use it to filter everything they read.

```mermaid
flowchart TB
    req["Incoming request"] --> health{"Path is /health?"}
    health -- "yes" --> open["Allowed, no auth"]
    health -- "no" --> key{"X-API-Key or<br/>Bearer token present?"}
    key -- "yes" --> dbkey{"Active key in<br/>api_keys? (hashed lookup)"}
    dbkey -- "yes" --> p1["Principal from the key:<br/>user, tenant, roles"]
    dbkey -- "no" --> legacy{"Matches VEKTOR_API_KEYS?"}
    legacy -- "yes" --> p2["Member of tenant 'default'"]
    legacy -- "no" --> deny["401"]
    key -- "no" --> dev{"Development mode and<br/>no keys configured?"}
    dev -- "yes" --> p3["Local admin 'dev'"]
    dev -- "no" --> deny
    p1 --> rl["Per-user rate limit"]
    p2 --> rl
    p3 --> rl
    rl --> repo["Repositories add tenant and owner filters"]
```

**Access rules**

| Resource | Who can read | Who can change or delete |
|---|---|---|
| Conversation | Its owner. A tenant admin can also open it, and that access is **audited** | Owner. A tenant admin can delete, audited |
| Document `private` | Owner only | Owner or tenant admin (audited) |
| Document `tenant` | Everyone in the tenant | Owner or tenant admin |
| Document `shared` | Owner and users with a grant | Owner or tenant admin |
| Usage numbers | The user sees their own. Admins see the whole tenant | n/a |
| Tenant budget | Everyone in the tenant | Admin only |

- Anything in another tenant, or not visible to you, returns **404**, not 403, so its existence is not revealed. A readable-but-not-yours resource returns 403 when you try to change it.
- Tenant admins can manage a document without being able to read a private one.
- **Three different kinds of keys exist. Do not mix them up.**

  | Key | Table | Purpose |
  |---|---|---|
  | Vektor API key | `api_keys` | Identifies a caller to this backend. Stored as a SHA-256 hash. Create with `python -m api.cli create-key`. |
  | Provider key (BYOK) | `provider_keys` | A tenant's own LLM provider credential, envelope-encrypted and bound to its tenant. |
  | Platform key | `platform_keys` | Pooled credentials used when a tenant is on the managed plan. |

See [`multi-user-design.md`](multi-user-design.md) for the reasoning behind these rules.

---

## 7. Data model

There is **no `tenants` or `users` table**. `tenant_id` and `user_id` are plain strings carried on every row, and the `Principal` supplies them. Relationship lines below are real foreign keys. Everything else is joined by `tenant_id` and `user_id` in queries.

### 7.1 Conversations and knowledge

```mermaid
erDiagram
    conversations ||--o{ conversation_messages : "contains"
    knowledge_documents ||--o{ knowledge_chunks : "split into"
    knowledge_documents ||--o{ document_grants : "shared through"
    conversations {
        string id PK
        string title
        int clarify_streak
        string tenant_id
        string owner_id
        datetime created_at
        datetime updated_at
    }
    conversation_messages {
        string id PK
        string conversation_id FK
        string role
        string content
        string provider
        string model
        int prompt_tokens
        int completion_tokens
        string status
    }
    knowledge_documents {
        string id PK
        string title
        string source
        string content_hash
        string embedding_model
        string tenant_id
        string owner_id
        string visibility
        datetime created_at
    }
    knowledge_chunks {
        string id PK
        string document_id FK
        int chunk_index
        string content
        string embedding_json
        string tenant_id
    }
    document_grants {
        string id PK
        string document_id FK
        string tenant_id
        string grantee_id
        string permission
        string created_by
        datetime created_at
    }
```
_Subset of columns:_ `conversation_messages` (9 of 12 columns shown).


### 7.2 Identity, usage, and billing

```mermaid
erDiagram

    api_keys {
        string id PK
        string tenant_id
        string user_id
        string key_hash
        string roles
        string label
        datetime created_at
        datetime expires_at
        datetime revoked_at
    }
    audit_logs {
        string id PK
        string tenant_id
        string actor_id
        string action
        string resource_type
        string resource_id
        string resource_owner_id
        datetime created_at
    }
    usage_events {
        string id PK
        string tenant_id
        string user_id
        string kind
        string provider
        string model
        int prompt_tokens
        int completion_tokens
        int total_tokens
    }
    tool_usage_events {
        string id PK
        string tenant_id
        string user_id
        string tool_name
        string status
        int duration_ms
        datetime created_at
    }
    message_feedback {
        string id PK
        string tenant_id
        string user_id
        string conversation_id
        string message_id
        string rating
        string comment
        datetime created_at
    }
    tenant_budgets {
        string tenant_id PK
        int monthly_token_limit
        float warn_ratio
        datetime updated_at
    }
    platform_keys {
        string id PK
        string provider
        string label
        string ciphertext
        string wrapped_dek
        string status
        int monthly_limit_micros
        datetime created_at
    }
    credit_ledger {
        string id PK
        string tenant_id
        string entry_type
        int amount_micros
        string ref_id
        datetime created_at
    }
    credit_reservations {
        string id PK
        string tenant_id
        int hold_micros
        string status
        datetime expires_at
        datetime created_at
    }
```
_Subset of columns:_ `usage_events` (9 of 10 columns shown).


### 7.3 Workflows and provider configuration

```mermaid
erDiagram
    workflows ||--o{ workflow_runs : "has runs"
    workflows {
        string id PK
        string tenant_id
        string owner_id
        string name
        string description
        string trigger_type
        string cron_expr
        string steps_json
        boolean enabled
    }
    workflow_runs {
        string id PK
        string workflow_id FK
        string tenant_id
        string triggered_by
        string status
        int current_step_index
        string input_json
        string context_json
        string step_logs_json
    }
    provider_settings {
        string id PK
        string tenant_id
        string user_id
        string provider
        string model
        string api_key_hash
        string base_url
        string connection_status
        string connection_error
    }
    provider_profiles {
        string id PK
        string tenant_id
        string user_id
        string label
        string provider
        string model
        string base_url
        string api_key_encrypted
        boolean is_default
    }
    provider_keys {
        string id PK
        string tenant_id
        string provider
        string label
        string ciphertext
        string wrapped_dek
        string last4
        string fingerprint
        string status
    }
    tenant_policies {
        string tenant_id PK
        string key_mode
        string allowed_models_json
        float daily_cap_usd
        boolean fallback_to_credits
        datetime updated_at
    }
    model_registry {
        string id PK
        string provider
        string tier
        int context_window
        string caps_json
        int price_in_micros
        int price_out_micros
        int price_cache_write_micros
        string status
    }
```
_Subset of columns:_ `workflows` (9 of 11 columns shown), `workflow_runs` (9 of 12 columns shown), `provider_settings` (9 of 13 columns shown), `provider_profiles` (9 of 11 columns shown), `provider_keys` (9 of 11 columns shown), `model_registry` (9 of 13 columns shown).


Schema changes go through Alembic migrations in `migrations/versions/` (see [section 11](#11-what-is-wired-in-and-what-is-not) for a problem with the current chain).

---

## 8. Workflows

A workflow is an ordered list of steps with a trigger (`manual`, `webhook`, or `cron`). The runner executes steps in order and can **pause for a human decision**.

| Step type | What it does |
|---|---|
| `knowledge_search` | Searches the knowledge base |
| `llm_step` | Calls the model with a prompt template |
| `tool_call` | Runs a registered tool through the same allowlist as chat |
| `human_approval` | Stops the run until someone approves or rejects it |

Steps can use earlier results through templates such as `{{ input.x }}` and `{{ steps.<step id>.output }}`.

```mermaid
stateDiagram-v2
    [*] --> running : start run
    running --> waiting_approval : reaches a human_approval step
    waiting_approval --> running : approve, continue with next step
    waiting_approval --> rejected : reject
    running --> completed : last step finished
    running --> failed : a step raised an error
    completed --> [*]
    rejected --> [*]
    failed --> [*]
```

Each run stores its step logs and context as JSON in `workflow_runs`, so a paused run can be resumed later, even after a restart.

---

## 9. Frontend

The web app is one client-side screen (`VektorApp`) that switches between views. It never talks to the backend directly. Every call goes through a Next.js route handler, which checks the destination and forwards the request.

```mermaid
flowchart TB
    subgraph browser["Browser"]
        app["VektorApp<br/>state: connection, session, messages, live turn"]
        subgraph views["Views"]
            chatv["Chat<br/>Sidebar, Composer, ChatMessage"]
            kv["Knowledge Base"]
            tv["Telemetry / Analytics"]
            wv["Workflows"]
            sv["Connection Settings"]
            pm["Profile dialog"]
        end
        subgraph lib["lib/"]
            api["api.ts<br/>requests, timeout, retry"]
            stream["stream.ts + sse.ts<br/>read server-sent events"]
            tw["typewriter.ts<br/>paced text reveal"]
            be["backend.ts<br/>route allowlist"]
        end
        ls[("localStorage<br/>connection, theme, name, activity")]
    end

    subgraph next["Next.js server"]
        route["Route handler under app/api/backend<br/>allowlisted routes, origin check,<br/>adds X-API-Key"]
    end

    be2["Backend API"]

    app --> views
    chatv --> stream --> tw
    views --> api
    api --> route
    stream --> route
    route --> be2
    app <--> ls
```

- **Why a proxy.** The API key and backend URL live in the browser, but requests are same-origin. The route handler only forwards paths listed in `lib/backend.ts` and only to the configured origin or `VEKTOR_ALLOWED_BACKEND_ORIGINS`.
- **Streaming UI.** `stream.ts` parses events and the typewriter reveals text at an adaptive pace, with a thinking indicator and live status before the first word. Pressing Stop (or Esc) aborts the request.
- **No backend session.** Authentication is the API key sent with every request. There is no cookie session.
- Tests: Vitest for `lib/`, Playwright for end-to-end flows in `frontend/e2e/`.

---

## 10. Deployment

```mermaid
flowchart LR
    subgraph dev["Local development"]
        d1["uvicorn :8000<br/>api.main:app"]
        d2["next dev :3000"]
        d3[("vektor.db<br/>SQLite file")]
        d2 --> d1 --> d3
    end

    subgraph prod["Production (recommended shape)"]
        gw["Your gateway / TLS"]
        web["Next.js server"]
        dock["Backend container<br/>Dockerfile, non-root"]
        pg[("PostgreSQL + pgvector")]
        gw --> web --> dock --> pg
    end

    mig["alembic upgrade head<br/>run by you, before release"]
    mig -.-> pg
```

- The **Dockerfile builds the backend only**. It does not contain the web app, the Alembic migrations, or the `docs` folder. Run migrations from a checkout, and deploy the frontend separately.
- Outside `development`, startup **fails** unless `VEKTOR_API_KEYS` is set. In `production`, it also fails if debug is on, and the API docs are turned off.
- The default SQLite file is for local use. Use PostgreSQL for anything shared.
- Not hardened for direct internet exposure. Put it behind your own gateway.

---

## 11. What is wired in and what is not

This table was produced by checking which code actually calls each piece, not by reading intentions.

| Capability | State | Notes |
|---|---|---|
| API-key auth, per-user rate limit, tenant and owner scoping | **On the chat path** | Applies to every authenticated route |
| Monthly tenant token budget | **On the chat path** | `require_budget` dependency on chat routes, `429` when exhausted |
| Usage metering (chat, rewrite, embedding, vision) | **On the chat path** | Written after the response |
| Hybrid retrieval, conditional rewrite, rerank, prune, confidence grading | **On the chat path** | |
| Grounding checks and the refusal gate | **On the chat path** | |
| Tool registry, risk gate, result cache | **On the chat path** | Built-ins include two mutating tools, blocked unless explicitly allowed |
| Per-user provider profiles | **On the chat path** | Resolved per turn |
| Skills catalogue in the prompt | **On the chat path** | |
| Conversation compaction | **Own endpoint** | `POST /conversations/{id}/compact` |
| Workflows | **Own endpoints** | `/api/v1/workflows` |
| MCP Apps widgets | **Own endpoints** | `/api/v1/mcp` |
| Messaging gateway | **Own endpoint** | Calls `ChatService`, so it shares the chat path |
| BYOK vault, tenant key policy, credit ledger, SSRF guard | **Own endpoints only** | `keys.py` uses them. **Chat calls do not resolve keys through `KeyResolver` and do not reserve or settle credits.** |
| Model registry (capability gating, versioned pricing) | **Not used by the app** | `ModelRegistryService` is only exercised by unit tests |
| Command sandbox | **Opt-in** | A disabled backend is the safe default. Docker and SSH are selected in settings. The tool is mutating |
| Parent-section expansion in retrieval | **Not implemented** | The retriever calls `expand_parent_sections` only if it exists, and no repository defines it, so this step is silently skipped |

**Known problems found while writing this page**

1. **Alembic has two heads.** `0008_tenant_budgets` and `0008_workflow_cron` both descend from `0007_workflows`, and `0009` continues from only one of them. `alembic upgrade head` will refuse to run until the branches are merged or re-chained.
2. **Parent expansion** (above) is a no-op until `expand_parent_sections` exists.
3. **Credits and BYOK are not enforced on chat.** If you advertise either, wire `KeyResolver` and `CreditLedgerService` into the provider used by `ChatService` first.

---

## 12. Where to look in the code

| If you want to… | Start here |
|---|---|
| Add an endpoint | `src/api/routers/`, then register it in `src/api/main.py` |
| Change how a chat turn works | `src/modules/ai_runtime/service.py` |
| Change retrieval or ranking | `src/modules/ai_runtime/retriever.py`, `reranker.py`, `src/modules/knowledge/repository.py` |
| Change how documents are split | `src/modules/knowledge/chunker.py`, `extractors.py` |
| Add a built-in tool | `src/modules/tools/builtins.py` (set `risk_level="mutating"` for anything that changes state) |
| Change auth or roles | `src/api/auth.py`, `src/modules/identity/` |
| Add a table | A `models.py`, a new migration in `migrations/versions/`, and the model import in `src/api/main.py` and `migrations/env.py` |
| Add a setting | `src/core/config/settings.py` and `.env.example` |
| Change the UI shell | `frontend/components/vektor-app.tsx` |
| Change how the UI calls the backend | `frontend/lib/api.ts`, `stream.ts`, and `frontend/app/api/backend/` |
| See what is tested | `tests/unit/` (no database) and `tests/integration/` (in-memory SQLite) |

Related documents: [`README.md`](../README.md), [`scope.md`](../scope.md), [`multi-user-design.md`](multi-user-design.md), [`plan-close-gaps.md`](plan-close-gaps.md).
