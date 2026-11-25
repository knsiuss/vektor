# Vektor

**An open-source, model-agnostic AI operations assistant.** Vektor lets teams ask questions about their own runbooks and documents, run read-only operational checks through tools, and keep track of what the AI did and what it cost.

> **Status: early development (v0.1.0).** Vektor is a working foundation, not a finished product. APIs and the database schema may change. Read [Known limitations](#known-limitations) before deploying it anywhere that matters.

## Features

- **Chat with grounded answers.** Multi-turn chat over an OpenAI-compatible API (OpenRouter by default), with server-sent-event streaming and a bounded tool-calling loop.
- **Knowledge base (RAG).** Upload PDF, DOCX, Markdown, text, CSV, JSON, and images. Documents are chunked, embedded, and searched with a hybrid semantic + lexical ranking, then reranked.
- **Answer verification without extra LLM calls.** Citations (`[n]`) are checked against the retrieved sources, and commands, hostnames, and error codes in an answer are checked against the context.
- **Tools with a safety gate.** Built-in read-only tools (`get_system_health`, `get_token_usage_report`, `search_knowledge_base`). Tools that change things are blocked unless the request explicitly allows them.
- **Web evidence without an API key.** `web_search` (SearXNG public instances, or your own) and `web_fetch` (SSRF-guarded, size- and type-limited). Fetched pages appear as citations with domain and retrieval date, and page text is treated as untrusted data.
- **Multi-tenant and multi-user.** Per-user API keys (stored hashed), `member` and `admin` roles, and conversations and documents scoped to their owner. Cross-tenant access returns `404`.
- **Document sharing.** Each document is `private`, visible to the whole `tenant`, or `shared` with specific users.
- **Admin oversight with an audit trail.** Tenant admins can read or delete other users' conversations, and every such access is written to an audit log.
- **Usage metering.** Every upstream model call (chat, query rewrite, embedding, vision) is recorded per tenant and user, with daily time series for the dashboard.
- **Web UI.** A Next.js app with the chat workspace, Knowledge Base, Telemetry / Analytics, and Connection Settings pages, plus a light and a dark theme.

## Project layout

```
.
├── src/
│   ├── api/            FastAPI app, middleware, auth, routers, admin CLI
│   ├── core/           Settings and database setup
│   └── modules/
│       ├── ai_runtime/     Chat service, retrieval, reranking, grounding checks
│       ├── knowledge/      Extraction, chunking, documents, hybrid search
│       ├── model_gateway/  OpenAI-compatible chat and embedding adapters
│       ├── conversations/  Conversations and messages
│       ├── identity/       Principals, API keys, audit log
│       ├── usage/          Usage events and metering
│       └── tools/          Tool registry and built-in tools
├── frontend/           Next.js 16 + React 19 web app
├── migrations/         Alembic migrations
├── tests/              Unit and integration tests
├── docs/               Design notes
└── scope.md            Product scope and long-term direction
```

For diagrams of how these parts fit together (request flow, RAG pipeline, access rules, data model, frontend), see [`docs/architecture.md`](docs/architecture.md).

## Quick start

**Requirements:** Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20+ (for the web UI), and an API key for an OpenAI-compatible provider.

### 1. Backend

```bash
git clone https://github.com/knsiuss/vektor.git
cd vektor

uv sync
cp .env.example .env          # on Windows: copy .env.example .env
# edit .env and set VEKTOR_LLM_API_KEY

uv run uvicorn api.main:app --reload --app-dir src
```

The API is now at <http://127.0.0.1:8000>, with interactive docs at `/docs` (development only) and a health check at `/health`.

In `development` with no API keys configured, the API is open and every request runs as a local admin. This is for local use only.

### 2. Web UI

```bash
cd frontend
npm install
npm run dev        # starts the backend (uvicorn --reload) and Next.js together
```

Open <http://localhost:3000>. The UI talks to the backend through a same-origin proxy. The default backend is `http://127.0.0.1:8000`, and you can change it, plus your API key, timeout, and retries, on the **Connection Settings** page. Use `npm run dev:next` if you only want the web app and already run the backend yourself.

## Configuration

All settings are environment variables with the `VEKTOR_` prefix, read from `.env`. See [`.env.example`](.env.example) for a starting point and [`src/core/config/settings.py`](src/core/config/settings.py) for the complete, validated list.

| Variable | Default | Purpose |
|---|---|---|
| `VEKTOR_APP_ENV` | `development` | `development`, `staging`, or `production`. |
| `VEKTOR_API_KEYS` | empty | Comma-separated shared keys. **Required outside development.** |
| `VEKTOR_DATABASE_URL` | `sqlite+aiosqlite:///./vektor.db` | Use `postgresql+asyncpg://...` for real deployments. |
| `VEKTOR_DB_AUTO_CREATE` | `true` | Create tables on startup. Set `false` if you manage the schema with Alembic. |
| `VEKTOR_LLM_API_KEY` | none | Key for your LLM provider. Keep it on the backend only. |
| `VEKTOR_LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint. |
| `VEKTOR_LLM_DEFAULT_MODEL` | `openai/gpt-4o-mini` | Chat model. |
| `VEKTOR_LLM_EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Embedding model. |
| `VEKTOR_LLM_EMBEDDING_BASE_URL`, `VEKTOR_LLM_EMBEDDING_API_KEY` | fall back to the LLM settings | Use a separate provider for embeddings. |
| `VEKTOR_LLM_VISION_MODEL` | falls back to the chat model | Extracts text from uploaded images. |
| `VEKTOR_LLM_REWRITE_MODEL` | none | Optional smaller model for query rewriting. |
| `VEKTOR_LLM_CHAT_TEMPERATURE` | `0.1` | Keep low for answers that must stay grounded. |
| `VEKTOR_RATE_LIMIT_PER_MINUTE` | `60` | Per-user request limit. |
| `VEKTOR_AGENT_MAX_HISTORY_TOKENS` | `3500` | Conversation history budget sent to the model. |
| `VEKTOR_RETRIEVAL_MAX_CONTEXT_TOKENS` | `2000` | Budget for retrieved document context. |
| `VEKTOR_WEB_SEARCH_PROVIDER` | `searxng` | Web search backend: `searxng` (no key) or `duckduckgo`. |
| `VEKTOR_WEB_SEARXNG_URL` | none | Your own SearXNG JSON endpoint; empty uses public instances. |
| `VEKTOR_WEB_MAX_SEARCHES`, `VEKTOR_WEB_MAX_FETCHES` | `3`, `3` | Per-turn web call limits. |

Outside `development`, startup fails unless `VEKTOR_API_KEYS` is set. In `production`, startup also fails if `VEKTOR_DEBUG` is on, and the API docs are turned off.

## Authentication and tenants

Every request carries an API key in the `X-API-Key` header (or `Authorization: [REDACTED_TOKEN]`). A key maps to a user, a tenant, and roles.

Create a per-user key from the backend:

```bash
uv run python -m api.cli create-key --tenant acme --user alice --roles admin
uv run python -m api.cli list-keys --tenant acme
uv run python -m api.cli revoke-key <key-id>
```

The key is shown once and only its hash is stored. Keys from `VEKTOR_API_KEYS` still work and act as a `member` of the `default` tenant. `GET /api/v1/me` returns who the backend thinks you are. The reasoning behind the access rules is in [`docs/multi-user-design.md`](docs/multi-user-design.md).

## API overview

| Area | Endpoints |
|---|---|
| Chat | `POST /api/v1/chat`, `POST /api/v1/chat/stream` (server-sent events) |
| Conversations | `GET /api/v1/conversations`, `GET` and `DELETE /api/v1/conversations/{id}` |
| Knowledge | `POST /api/v1/knowledge/documents`, `POST .../documents/upload`, `GET .../documents`, `POST .../search`, `DELETE .../documents/{id}`, `PATCH .../documents/{id}/visibility`, `GET` and `POST .../documents/{id}/grants` |
| Usage | `GET /api/v1/usage`, `/usage/breakdown`, `/usage/timeseries?days=30` |
| Identity | `GET /api/v1/me` |
| Admin | `GET /api/v1/admin/conversations`, `/admin/usage`, `/admin/usage/breakdown`, `/admin/audit-log` |
| System | `GET /health` |

Full request and response schemas are in the interactive docs at `/docs`.

## Database migrations

Fresh development databases are created automatically. For an existing database, or when you set `VEKTOR_DB_AUTO_CREATE=false`, use Alembic:

```bash
uv add alembic        # Alembic is not yet a declared dependency
uv run alembic upgrade head
```

Back up your database before upgrading. Conversations and documents that existed before multi-tenancy are assigned to the `default` tenant.

## Docker

```bash
docker build -t vektor .
docker run -p 8000:8000 --env-file .env vektor
```

The image contains the backend only. It does not include the web UI or the Alembic migrations. For production, set `VEKTOR_APP_ENV=production`, set `VEKTOR_API_KEYS`, and point `VEKTOR_DATABASE_URL` at PostgreSQL.

## Development

```bash
uv run pytest tests -q --ignore=tests/e2e     # backend tests
uv run ruff check .                            # lint
uv run mypy                                    # type check (strict)

cd frontend
npm run typecheck && npm test                  # frontend checks
npm run test:e2e                               # Playwright (needs both servers running)
```

## Known limitations

- **Vector search runs in-process.** Embeddings are stored as JSON and compared in Python, which is fine for small knowledge bases and slow for large ones. A pgvector backend is the intended next step.
- **Authentication is API-key based.** OIDC / JWT sign-in, Postgres row-level security, and role-based document grants are designed but not built.
- **No MCP support yet.** MCP compatibility is part of the product direction in [`scope.md`](scope.md), not something the code does today.
- **Tool usage is not recorded per answer**, so the Telemetry page cannot rank tools yet.
- **Costs are token counts, not currency.** There is no price table yet.
- **Not hardened for the public internet.** Put it behind your own gateway, and review the settings above before exposing it.

## Contributing

Issues and pull requests are welcome. Please run the test, lint, and type checks above before opening a pull request, and keep changes focused. For larger changes, open an issue first so the direction can be agreed.

## License

Vektor is released under the [MIT License](LICENSE).

Unless you explicitly state otherwise, any contribution you intentionally submit for inclusion in this project is licensed under the same terms, without any additional conditions.
