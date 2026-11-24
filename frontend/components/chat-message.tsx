"use client";

import { useEffect, useId, useState } from "react";
import Markdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import SyntaxHighlighter from "react-syntax-highlighter";
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs";

import type { Citation, Connection, GroundingReport, ToolCall } from "@/lib/types";
import { formatDate } from "@/lib/format";

import { Brain, Check, ChevronDown, CircleAlert, Copy, FileText, LoaderCircle, Settings2, ShieldAlert, ThumbsDown, ThumbsUp, VektorLogo } from "./icons";
import { McpAppFrame } from "./mcp-app-frame";

function CodeBlock({ language, value }: { language?: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="code-block">
      <div className="code-toolbar">
        <span>{language || "code"}</span>
        <button onClick={copy} aria-label={copied ? "Code copied" : "Copy code"}>
          {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={atomOneDark}
        customStyle={{ margin: 0, padding: "20px", background: "transparent", fontSize: "13px" }}
        wrapLongLines
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
}

function MermaidDiagram({ value }: { value: string }) {
  const reactId = useId().replace(/:/g, "");
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<boolean>(false);
  const [showCode, setShowCode] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;
    async function renderDiagram() {
      try {
        const mermaid = (await import("mermaid")).default;
        const isDark = document.documentElement.dataset.theme === "dark";
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: isDark ? "dark" : "neutral",
        });
        const { svg: rendered } = await mermaid.render(`vektor-mermaid-${reactId}`, value);
        if (!cancelled) {
          setSvg(rendered);
          setError(false);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    }
    void renderDiagram();
    return () => {
      cancelled = true;
    };
  }, [reactId, value]);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  if (error && !svg) {
    return <CodeBlock language="mermaid" value={value} />;
  }

  return (
    <div className="mermaid-card">
      <div className="code-toolbar">
        <span>mermaid</span>
        <div className="mermaid-actions">
          <button type="button" onClick={() => setShowCode((v) => !v)}>
            {showCode ? "Diagram" : "Code"}
          </button>
          <button type="button" onClick={copy} aria-label={copied ? "Code copied" : "Copy diagram source"}>
            {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      {showCode ? (
        <pre className="mermaid-source">{value}</pre>
      ) : (
        <div
          className="mermaid-canvas"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}
    </div>
  );
}

function preprocessMarkdown(raw: string): string {
  // Normalize \[...\] and \(...\) outside fenced code blocks so remark-math renders them.
  const segments = raw.split(/(```[\s\S]*?```)/g);
  return segments
    .map((segment, idx) => {
      if (idx % 2 === 1) return segment;
      return segment
        .replace(/\\\[([\s\S]*?)\\\]/g, (_m, inner: string) => `\n$$\n${inner.trim()}\n$$\n`)
        .replace(/\\\((.+?)\\\)/g, (_m, inner: string) => `$${inner.trim()}$`);
    })
    .join("");
}

function ToolTrace({ tool }: { tool: ToolCall }) {
  return (
    <details className={`tool-trace ${tool.status}`}>
      <summary>
        <Settings2 size={15} aria-hidden="true" />
        <span>{tool.status === "blocked" ? "Blocked" : tool.status === "error" ? "Failed" : "Executed"} <code>{tool.tool_name}</code></span>
        <span className={`status-word ${tool.status}`}>{tool.status}</span>
        <ChevronDown size={15} className="details-chevron" aria-hidden="true" />
      </summary>
      <div className="tool-details">
        <h4>Input arguments</h4>
        <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
        <h4>Tool response</h4>
        <pre>{tool.output}</pre>
      </div>
    </details>
  );
}

function CitationRow({ citation, index }: { citation: Citation; index: number }) {
  const isWeb = citation.kind === "web" && Boolean(citation.url);
  let host = "";
  if (isWeb) {
    try {
      host = new URL(citation.url as string).hostname.replace(/^www\./, "");
    } catch {
      host = citation.url ?? "";
    }
  }
  return (
    <details className="citation">
      <summary>
        <span className="citation-index">[{index}]</span>
        <FileText size={15} aria-hidden="true" />
        {isWeb ? (
          <a href={citation.url as string} target="_blank" rel="noreferrer">{citation.document_title}</a>
        ) : (
          <span>{citation.document_title}</span>
        )}
        {isWeb ? (
          <span className="match-score web-source">{host}{citation.retrieved_at ? ` \u00b7 ${formatDate(citation.retrieved_at)}` : ""}</span>
        ) : (
          <span className="match-score">{Math.round(citation.score * 100)}% match</span>
        )}
      </summary>
      <div className="citation-content">
        <p>{citation.content}</p>
        <span>{isWeb ? "Fetched page" : `Chunk ${citation.chunk_index + 1}`}</span>
      </div>
    </details>
  );
}

function CitationList({ citations, grounding }: { citations: Citation[]; grounding?: GroundingReport | null }) {
  const [showUncited, setShowUncited] = useState(false);

  const hasCitedSubset = Boolean(grounding && grounding.cited_indices.length > 0);
  const citedSet = new Set(grounding?.cited_indices ?? []);

  const primaryCitations = hasCitedSubset
    ? citations.map((citation, idx) => ({ citation, index: idx + 1 })).filter(({ index }) => citedSet.has(index))
    : citations.map((citation, idx) => ({ citation, index: idx + 1 }));

  const uncitedCitations = hasCitedSubset
    ? citations.map((citation, idx) => ({ citation, index: idx + 1 })).filter(({ index }) => !citedSet.has(index))
    : [];

  return (
    <div className="citations">
      <div className="citations-header">
        <p className="citations-title">
          {hasCitedSubset ? `Cited sources (${primaryCitations.length})` : "Retrieved sources"}
        </p>
        {uncitedCitations.length > 0 && (
          <button type="button" className="text-button" onClick={() => setShowUncited((value) => !value)}>
            {showUncited ? "Hide uncited excerpts" : `Show ${uncitedCitations.length} uncited retrieved excerpt${uncitedCitations.length === 1 ? "" : "s"}`}
          </button>
        )}
      </div>
      {primaryCitations.length > 0 && (
        <div className="citation-list">
          {primaryCitations.map(({ citation, index }) => (
            <CitationRow key={`${citation.document_id}-${citation.chunk_index}`} citation={citation} index={index} />
          ))}
        </div>
      )}
      {showUncited && uncitedCitations.length > 0 && (
        <div className="citation-list uncited-list">
          {uncitedCitations.map(({ citation, index }) => (
            <CitationRow key={`${citation.document_id}-${citation.chunk_index}`} citation={citation} index={index} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReasoningTrace({ reasoning, streaming = false }: { reasoning: string; streaming?: boolean }) {
  return (
    <details className="reasoning-trace" open={streaming}>
      <summary>
        <Brain size={15} aria-hidden="true" />
        <span>{streaming ? "Thinking..." : "Thought process"}</span>
        <span className="status-word reasoning">{streaming ? "live" : "thinking"}</span>
        <ChevronDown size={15} className="details-chevron" aria-hidden="true" />
      </summary>
      <div className="reasoning-details">{reasoning}</div>
    </details>
  );
}

function GroundingWarnings({ grounding }: { grounding: GroundingReport }) {
  const hasWarnings =
    grounding.invalid_citations.length > 0 ||
    grounding.ungrounded_tokens.length > 0;
  if (!hasWarnings) return null;

  return (
    <div className="grounding-banner" role="status">
      <CircleAlert size={18} aria-hidden="true" />
      <div>
        <strong>Grounding verification notice</strong>
        <ul>
          {grounding.has_context_without_citations && (
            <li>Retrieved documents were provided, but this answer contains no inline <code>[n]</code> citations.</li>
          )}
          {grounding.invalid_citations.length > 0 && (
            <li>Invalid citation index referenced: {grounding.invalid_citations.map((idx) => `[${idx}]`).join(", ")}.</li>
          )}
          {grounding.ungrounded_tokens.length > 0 && (
            <li>
              Not found in retrieved documents or tool outputs:{" "}
              {grounding.ungrounded_tokens.map((tok) => <code key={tok}>{tok}</code>)}
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

export function MessageContent({ content }: { content: string }) {
  const normalized = preprocessMarkdown(content);
  return (
    <Markdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        pre({ children }) { return <>{children}</>; },
        table({ children }) {
          return (
            <div className="markdown-table-wrap">
              <table>{children}</table>
            </div>
          );
        },
        code({ className, children, ...props }) {
          const language = /language-([\w-]+)/.exec(className || "")?.[1]?.toLowerCase();
          const value = String(children).replace(/\n$/, "");
          if (language === "mermaid") return <MermaidDiagram value={value} />;
          if (language || value.includes("\n")) return <CodeBlock language={language} value={value} />;
          return <code className={className} {...props}>{children}</code>;
        },
        a({ children, ...props }) { return <a {...props} target="_blank" rel="noreferrer">{children}</a>; },
      }}
    >
      {normalized}
    </Markdown>
  );
}

export function ChatMessage({
  message,
  onApprove,
  onCancel,
  onFeedback,
  actionPending,
  streaming = false,
  connection,
  onWidgetMessage,
  onWidgetState,
  onChooseOption,
}: {
  message: {
    id: string;
    role: "user" | "assistant";
    content: string;
    model: string | null;
    citations?: unknown[];
    toolCalls?: unknown[];
    grounding?: GroundingReport | null;
    reasoning?: string | null;
    status?: "answer" | "clarify" | "unknown" | null;
    clarify_options?: string[] | null;
    error?: boolean;
    usage?: { cached_tokens?: number; total_tokens?: number } | null;
    created_at: string;
  };
  onApprove: (message: string) => void;
  onCancel: () => void;
  onFeedback?: (messageId: string, rating: "up" | "down") => void;
  actionPending: boolean;
  /** True while this answer is still being written: hides actions that need a finished answer. */
  streaming?: boolean;
  connection?: Connection;
  onWidgetMessage?: (text: string) => void;
  onWidgetState?: (callId: string, state: unknown) => void;
  /** Clarification options are sent as the next user message. */
  onChooseOption?: (text: string) => void;
}) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);

  if (message.role === "user") {
    return <article className="user-message"><div className="user-bubble">{message.content}</div></article>;
  }

  if (message.error) {
    return (
      <article className="assistant-message error-message" role="alert">
        <div className="assistant-avatar"><CircleAlert size={17} aria-hidden="true" /></div>
        <div className="assistant-content">
          <div className="message-author">Vektor <span>Request failed</span></div>
          <div className="error-bubble">
            <p>{message.content}</p>
            <span className="error-hint">Your message was sent, but the provider returned no answer. Try again in a moment.</span>
          </div>
        </div>
      </article>
    );
  }

  if (message.status === "clarify" && !streaming) {
    const options = message.clarify_options ?? [];
    return (
      <article className="assistant-message clarify-message">
        <div className="assistant-avatar"><VektorLogo size={24} /></div>
        <div className="assistant-content">
          <div className="message-author">Vektor <span>needs one detail</span></div>
          <div className="clarify-card">
            <p className="clarify-question">{message.content}</p>
            {options.length > 0 && (
              <div className="clarify-options" role="group" aria-label="Suggested answers">
                {options.map((option) => (
                  <button
                    type="button"
                    key={option}
                    onClick={() => onChooseOption?.(option)}
                    disabled={actionPending}
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </article>
    );
  }

function formatArguments(args: Record<string, unknown> | undefined): string {
  if (!args || Object.keys(args).length === 0) return "no arguments";
  const text = JSON.stringify(args, null, 2);
  return text.length > 400 ? `${text.slice(0, 400)}…` : text;
}

  const blockedTools = streaming ? [] : (message.toolCalls as ToolCall[] | undefined)?.filter((tool) => tool.status === "blocked") ?? [];
  const chooseRating = (next: "up" | "down") => {
    setRating(next);
    onFeedback?.(message.id, next);
  };
  return (
    <article className="assistant-message">
      <div className="assistant-avatar"><VektorLogo size={24} /></div>
      <div className="assistant-content">
        <div className="message-author">
          Vektor <span>{message.model || "Operations assistant"}</span>
          {message.status === "unknown" && <span className="msg-meta-pill">No data found</span>}
          {message.model === "grounded-gate" && (
            <span className="msg-meta-pill">Grounded refusal</span>
          )}
          {message.usage?.cached_tokens ? (
            <span className="msg-meta-pill">
              Cache hit: {message.usage.cached_tokens} tok
            </span>
          ) : null}
        </div>
        {(message.toolCalls as ToolCall[] | undefined)?.map((tool) => <ToolTrace key={tool.call_id} tool={tool} />)}
        {connection &&
          (message.toolCalls as ToolCall[] | undefined)
            ?.filter((tool) => Boolean(tool.ui_resource_uri))
            .map((tool) => (
              <McpAppFrame
                key={`widget-${tool.call_id}`}
                tool={tool}
                connection={connection}
                onSendMessage={onWidgetMessage}
                onWidgetState={onWidgetState}
              />
            ))}
        {blockedTools.length > 0 && (
          <div className="approval-banner" role="alert">
            <ShieldAlert size={21} aria-hidden="true" />
            <div>
              <strong>{blockedTools.map((tool) => tool.tool_name).join(", ")} requires approval</strong>
              <p>This tool can change your infrastructure. Approving repeats this instruction and allows every mutating tool in the new turn.</p>
              <ul className="approval-preview">
                {blockedTools.map((tool) => (
                  <li key={tool.call_id}>
                    <code>{tool.tool_name}</code>
                    <pre>{formatArguments(tool.arguments)}</pre>
                  </li>
                ))}
              </ul>
              <div className="approval-actions">
                <button className="button danger" onClick={() => onApprove(message.content)} disabled={actionPending}>
                  {actionPending ? <LoaderCircle size={15} className="spin" aria-hidden="true" /> : null}
                  Approve and run
                </button>
                <button className="button secondary" onClick={onCancel} disabled={actionPending}>Cancel</button>
              </div>
            </div>
          </div>
        )}
        {!streaming && message.grounding && <GroundingWarnings grounding={message.grounding} />}
        {message.reasoning ? <ReasoningTrace reasoning={message.reasoning} streaming={streaming} /> : null}
        <div className={streaming ? "markdown is-streaming" : "markdown"}><MessageContent content={message.content} /></div>
        {message.citations && (message.citations as Citation[]).length > 0 && (
          <CitationList citations={message.citations as Citation[]} grounding={message.grounding} />
        )}
        {onFeedback && !streaming && (
          <div className="feedback-row" aria-label="Response feedback">
            <button
              type="button"
              className={`feedback-btn ${rating === "up" ? "is-active" : ""}`}
              aria-label="Helpful response"
              aria-pressed={rating === "up"}
              onClick={() => chooseRating("up")}
            >
              <ThumbsUp size={14} aria-hidden="true" />
            </button>
            <button
              type="button"
              className={`feedback-btn ${rating === "down" ? "is-active" : ""}`}
              aria-label="Unhelpful response"
              aria-pressed={rating === "down"}
              onClick={() => chooseRating("down")}
            >
              <ThumbsDown size={14} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

export function PendingMessage({ status }: { status?: string | null }) {
  // The backend words its progress as "Searching knowledge base..."; the dots already say "working".
  const label = status ? status.replace(/(?:\.{2,}|\u2026)\s*$/, "") : "Thinking";
  return (
    <div className="assistant-message pending-message" role="status" aria-live="polite">
      <div className="assistant-avatar"><VektorLogo size={24} /></div>
      <div className="pending-copy">
        <span className="thinking-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="thinking-label">{label}</span>
      </div>
    </div>
  );
}
