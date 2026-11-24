"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  addActivity,
  loadActivity,
  loadFirstSeen,
  loadProfileName,
  loadTheme,
  saveProfileName,
  saveTheme,
} from "@/lib/activity";
import type { ActivityItem, Theme } from "@/lib/activity";
import { api, ApiError, compactConversation } from "@/lib/api";
import { streamChat } from "@/lib/stream";
import { Typewriter } from "@/lib/typewriter";
import { approvalTarget, mapMessages } from "@/lib/conversations";
import { initials, nameFromUserId } from "@/lib/format";
import type {
  ChatRequest,
  ChatStreamEvent,
  Citation,
  Connection,
  ConnectionCheck,
  ConversationContext,
  ConversationDetail,
  GroundingReport,
  KnowledgeDocument,
  LiveTurn,
  Me,
  Message,
  ReasoningEffort,
  RetrievalMode,
  ToolCall,
  Usage,
  View,
} from "@/lib/types";

import { ChatMessage, PendingMessage } from "./chat-message";
import { Composer } from "./composer";
import { ConfirmDialog } from "./drawer";
import { Activity, BarChart3, BookOpen, ChevronRight, Cpu, Search, Settings, SidebarToggle, VektorLogo } from "./icons";
import { KnowledgeView } from "./knowledge-view";
import { LoginScreen } from "./login-screen";
import { ProfileModal } from "./profile-modal";
import { DEFAULT_CONNECTION, SettingsView } from "./settings-view";
import { Sidebar } from "./sidebar";
import { TelemetryView } from "./telemetry-view";
import { WorkflowsView } from "./workflows-view";

const CONNECTION_KEY = "vektor:connection";

const CHECKING: ConnectionCheck = {
  status: "checking",
  auth: "unknown",
  latencyMs: null,
  checkedAt: null,
  model: null,
  error: null,
};

const STARTERS: { title: string; desc: string; query: string; icon: ReactNode }[] = [
  { title: "Check database health", desc: "Run a system health diagnosis through available read-only tools.", query: "Check database health", icon: <Activity className="starter-icon" size={26} aria-hidden="true" /> },
  { title: "Find failover runbook", desc: "Search the knowledge base for indexed operational documents.", query: "Find the database failover runbook", icon: <BookOpen className="starter-icon" size={26} aria-hidden="true" /> },
  { title: "Show system metrics", desc: "Query observability endpoints recorded by your backend.", query: "Show system metrics", icon: <BarChart3 className="starter-icon" size={26} aria-hidden="true" /> },
  { title: "Search knowledge base", desc: "Run hybrid retrieval across your indexed documents.", query: "Search knowledge base for infrastructure incidents", icon: <Search className="starter-icon" size={26} aria-hidden="true" /> },
];

type ConversationSummary = { id: string; title: string; updated_at: string };

function parseConnection(raw: string | null): Connection {
  try {
    const parsed = JSON.parse(raw ?? "{}") as Record<string, unknown>;
    return {
      baseUrl: typeof parsed.baseUrl === "string" && parsed.baseUrl ? parsed.baseUrl : DEFAULT_CONNECTION.baseUrl,
      apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : "",
      timeoutSeconds: typeof parsed.timeoutSeconds === "number" ? parsed.timeoutSeconds : DEFAULT_CONNECTION.timeoutSeconds,
      maxRetries: typeof parsed.maxRetries === "number" ? parsed.maxRetries : DEFAULT_CONNECTION.maxRetries,
      extraHeaders: typeof parsed.extraHeaders === "string" ? parsed.extraHeaders : "",
    };
  } catch {
    return { ...DEFAULT_CONNECTION };
  }
}

function persistConnection(connection: Connection) {
  try {
    localStorage.setItem(CONNECTION_KEY, JSON.stringify(connection));
  } catch {
    // localStorage unavailable: continue without persistence.
  }
}

async function checkBackend(connection: Connection): Promise<ConnectionCheck> {
  const started = performance.now();
  const elapsed = () => Math.round(performance.now() - started);
  try {
    const usage = await api<Usage>("usage", connection, {
      retries: 0,
      timeoutMs: Math.min((connection.timeoutSeconds ?? 30) * 1000, 15_000),
    });
    return {
      status: "connected",
      auth: connection.apiKey ? "valid" : "unknown",
      latencyMs: elapsed(),
      checkedAt: new Date().toISOString(),
      model: usage.by_model[0]?.model ?? null,
      error: null,
    };
  } catch (cause) {
    const status = cause instanceof ApiError ? cause.status : 0;
    return {
      status: "disconnected",
      auth: status === 401 || status === 403 ? "invalid" : "unknown",
      latencyMs: status > 0 ? elapsed() : null,
      checkedAt: new Date().toISOString(),
      model: null,
      error: cause instanceof Error ? cause.message : "Could not reach the backend.",
    };
  }
}

export function VektorApp() {
  const [hydrated, setHydrated] = useState(false);
  const [connection, setConnection] = useState<Connection>({ ...DEFAULT_CONNECTION });
  const [check, setCheck] = useState<ConnectionCheck>(CHECKING);
  const [me, setMe] = useState<Me | null>(null);
  const [authState, setAuthState] = useState<"checking" | "ready" | "required">("checking");
  const [authReason, setAuthReason] = useState<string | null>(null);

  const [view, setView] = useState<View>("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarHidden, setSidebarHidden] = useState(true);
  const [profileOpen, setProfileOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>("dark");
  const [customName, setCustomName] = useState<string | null>(null);
  const [firstSeen, setFirstSeen] = useState(() => new Date().toISOString());
  const [activity, setActivity] = useState<ActivityItem[]>([]);

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [context, setContext] = useState<ConversationContext | null>(null);
  const [compacting, setCompacting] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState<string | null>(null);

  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("auto");
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort | null>(null);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const [modelContextLength, setModelContextLength] = useState<number | null>(null);
  const [documentScope, setDocumentScope] = useState("");
  const [allowMutatingTools, setAllowMutatingTools] = useState(false);
  const [composerValue, setComposerValue] = useState("");
  const [composerDisabled, setComposerDisabled] = useState(false);
  const [live, setLive] = useState<LiveTurn | null>(null);

  // Stop button: the turn in flight (its abort controller and typewriter), and a counter that
  // lets late work from a stopped turn notice that a newer turn has started.
  const abortRef = useRef<AbortController | null>(null);
  const typerRef = useRef<Typewriter | null>(null);
  const stopRequested = useRef(false);
  const runId = useRef(0);

  // Follow the answer as it is written, unless the reader has scrolled up to read something else.
  const mainRef = useRef<HTMLElement | null>(null);
  const stickToBottom = useRef(true);
  const handleMainScroll = () => {
    const el = mainRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
  };
  useEffect(() => {
    stickToBottom.current = true;
  }, [view]);
  useEffect(() => {
    const el = mainRef.current;
    if (el && view === "chat" && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages, live, view]);

  const record = useCallback((label: string, kind: ActivityItem["kind"]) => setActivity(addActivity(label, kind)), []);

  // Restore browser-only state after hydration so server and client markup match.
  useEffect(() => {
    try {
      setConnection(parseConnection(localStorage.getItem(CONNECTION_KEY)));
    } catch {
      // localStorage unavailable: continue with defaults.
    }
    setTheme(loadTheme());
    setCustomName(loadProfileName());
    setFirstSeen(loadFirstSeen());
    setActivity(loadActivity());
    setHydrated(true);
  }, []);

  useEffect(() => {
    // Wait for hydration so the pre-paint script's saved choice survives the first render.
    if (hydrated) document.documentElement.dataset.theme = theme;
  }, [theme, hydrated]);

  // Ask the backend who we are; a 401 means OAuth login is required on this deployment.
  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    api<{ user_id: string }>("auth/me", connection, { retries: 0 })
      .then(() => {
        if (!cancelled) setAuthState("ready");
      })
      .catch((cause) => {
        if (cancelled) return;
        const status = cause instanceof ApiError ? cause.status : 0;
        setAuthState(status === 401 ? "required" : "ready");
        if (status === 401) {
          setAuthReason(
            new URLSearchParams(window.location.search).get("login") === "failed"
              ? "The provider did not accept the sign-in. Please try again."
              : null,
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [connection, hydrated]);

    // Verify the backend whenever the connection changes.
  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    setCheck(CHECKING);
    void (async () => {
      const result = await checkBackend(connection);
      if (cancelled) return;
      setCheck(result);
      if (result.status !== "connected") {
        setMe(null);
        return;
      }
      try {
        const identity = await api<Me>("me", connection, { retries: 0 });
        if (!cancelled) setMe(identity);
      } catch {
        if (!cancelled) setMe(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrated, connection]);

  const refreshConversations = useCallback(async () => {
    setLoadingConversations(true);
    setConversationsError(null);
    try {
      setConversations(await api<ConversationSummary[]>("conversations", connection));
    } catch (cause) {
      setConversationsError(cause instanceof Error ? cause.message : "Could not load conversations.");
    } finally {
      setLoadingConversations(false);
    }
  }, [connection]);

  const refreshDocuments = useCallback(async () => {
    setDocumentsLoading(true);
    setDocumentsError(null);
    try {
      setDocuments(await api<KnowledgeDocument[]>("knowledge/documents", connection));
    } catch (cause) {
      setDocumentsError(cause instanceof Error ? cause.message : "Could not load indexed documents.");
    } finally {
      setDocumentsLoading(false);
    }
  }, [connection]);

  useEffect(() => {
    if (!hydrated) return;
    void refreshConversations();
    void refreshDocuments();
  }, [hydrated, refreshConversations, refreshDocuments]);

  const focusComposer = () => document.getElementById("message-input")?.focus();
  const closeMobileSidebar = () => {
    if (window.innerWidth < 768) setSidebarOpen(false);
  };

  const navigate = useCallback((next: View) => {
    setView(next);
    closeMobileSidebar();
    if (next === "knowledge") {
      void refreshDocuments();
      record("Viewed knowledge base", "knowledge");
    }
  }, [record, refreshDocuments]);

  const selectConversation = useCallback(async (id: string) => {
    setView("chat");
    setActiveId(id);
    setSidebarHidden(true);
    stickToBottom.current = true;
    setChatError(null);
    closeMobileSidebar();
    try {
      const detail = await api<ConversationDetail>(`conversations/${id}`, connection);
      setMessages(mapMessages(detail));
      setContext(detail.context ?? null);
    } catch (cause) {
      setChatError(cause instanceof Error ? cause.message : "Could not open this conversation.");
    }
  }, [connection]);

  const startNewSession = useCallback(() => {
    setView("chat");
    setActiveId(null);
    setSidebarHidden(true);
    setMessages([]);
    setContext(null);
    setChatError(null);
    closeMobileSidebar();
    window.setTimeout(focusComposer, 0);
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api(`conversations/${pendingDelete.id}`, connection, { method: "DELETE" });
      setConversations((list) => list.filter((item) => item.id !== pendingDelete.id));
      if (activeId === pendingDelete.id) {
        setActiveId(null);
        setMessages([]);
        setContext(null);
      }
    } catch (cause) {
      setChatError(cause instanceof Error ? cause.message : "Could not delete this session.");
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }, [pendingDelete, connection, activeId]);

  const compactHistory = useCallback(async () => {
    if (!activeId || compacting) return;
    setCompacting(true);
    setChatError(null);
    try {
      const detail = await compactConversation(connection, activeId);
      setMessages(mapMessages(detail));
      setContext(detail.context ?? null);
      record("Compacted conversation context", "session");
      void refreshConversations();
    } catch (cause) {
      setChatError(cause instanceof Error ? cause.message : "Could not compact this conversation.");
    } finally {
      setCompacting(false);
    }
  }, [activeId, compacting, connection, record, refreshConversations]);

  const runChat = useCallback(async (message: string, approve?: boolean) => {
    const text = message.trim();
    if (!text) return;
    setComposerDisabled(true);
    setChatError(null);
    setComposerValue("");
    stickToBottom.current = true;
    setMessages((current) => [
      ...current,
      { id: `pending-${Date.now()}`, role: "user", content: text, model: null, created_at: new Date().toISOString() },
    ]);
    setLive({ text: "", status: null, reasoning: "", citations: [], toolCalls: [], model: null });

    const startedNewSession = activeId === null;
    const myRun = ++runId.current;
    const controller = new AbortController();
    abortRef.current = controller;
    stopRequested.current = false;
    // Messages the server already holds, to recognise when it has also saved a stopped turn.
    // Turns that failed or were stopped only exist in the transcript, so they cannot be counted.
    const knownOnServer = messages.filter((item) => !/^(pending|stopped|failed)-/.test(item.id)).length;
    const patchLive = (patch: Partial<LiveTurn>) =>
      setLive((current) => (current ? { ...current, ...patch } : current));
    let revealed = "";
    const typer = new Typewriter((visible) => {
      revealed = visible;
      patchLive({ text: visible });
    });
    typerRef.current = typer;

    // Collected from the stream; used after it ends to attach evidence to the saved answer.
    const turn: {
      conversationId: string | null;
      grounding: GroundingReport | null;
      reasoning: string;
      citations: Citation[];
      toolCalls: ToolCall[];
      usage: Message["usage"];
      failure: string | null;
    } = { conversationId: activeId, grounding: null, reasoning: "", citations: [], toolCalls: [], usage: null, failure: null };

    // After a stop the backend saves the text it had sent. Adopt that saved copy once it is
    // there, so the next message continues the same session; keep the local copy until then.
    const adoptSavedTurn = async () => {
      const id = turn.conversationId;
      if (!id) return;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        if (attempt > 0) await new Promise((resolve) => window.setTimeout(resolve, 300));
        if (runId.current !== myRun) return;
        try {
          const detail = await api<ConversationDetail>(`conversations/${id}`, connection, { retries: 0 });
          if (detail.messages.length < knownOnServer + 2) continue;
          if (runId.current !== myRun) return;
          const mapped = mapMessages(detail);
          const last = mapped.map((item) => item.role).lastIndexOf("assistant");
          if (last >= 0) mapped[last] = { ...mapped[last], citations: turn.citations, toolCalls: turn.toolCalls };
          setActiveId(id);
          setMessages(mapped);
          void refreshConversations();
          if (startedNewSession) record("Started a new session", "session");
          return;
        } catch {
          // Not saved yet, or the backend is unreachable: try again.
        }
      }
    };

    const onEvent = (event: ChatStreamEvent) => {
      switch (event.event) {
        case "meta":
          if (event.conversation_id) turn.conversationId = event.conversation_id;
          break;
        case "status":
          patchLive({ status: event.status ?? null });
          break;
        case "citations":
          turn.citations = event.citations ?? [];
          patchLive({ citations: turn.citations });
          break;
        case "tool":
          turn.toolCalls = [...turn.toolCalls, ...(event.tool_calls ?? [])];
          patchLive({ toolCalls: turn.toolCalls });
          break;
        case "reasoning":
          turn.reasoning += event.reasoning ?? "";
          patchLive({ reasoning: turn.reasoning });
          break;
        case "delta":
          // Text means the previous step is over, so its progress message no longer applies.
          patchLive({ status: null });
          typer.push(event.delta ?? "");
          break;
        case "done":
          if (event.conversation_id) turn.conversationId = event.conversation_id;
          if (event.model) patchLive({ model: event.model });
          turn.grounding = event.grounding ?? null;
          turn.usage = event.usage ?? null;
          if (event.reasoning) turn.reasoning = event.reasoning;
          break;
        case "error":
          turn.failure = event.detail ?? "The assistant could not finish this answer.";
          break;
      }
    };

    try {
      const payload: ChatRequest = {
        message: text,
        conversation_id: activeId ?? undefined,
        ...(selectedModel ? { model: selectedModel } : {}),
        ...(selectedProfileId ? { provider_profile_id: selectedProfileId } : {}),
        retrieval_mode: retrievalMode,
        ...(retrievalMode === "explicit" && documentScope ? { document_ids: [documentScope] } : {}),
        allow_mutating_tools: allowMutatingTools || !!approve,
        reasoning_effort: reasoningEffort,
      };
      await streamChat(connection, payload, onEvent, controller.signal);
      if (turn.failure) throw new Error(turn.failure);
      await typer.finish();
      if (!turn.conversationId) throw new Error("The answer finished, but the session could not be identified.");

      setActiveId(turn.conversationId);
      const [detail] = await Promise.all([
        api<ConversationDetail>(`conversations/${turn.conversationId}`, connection),
        refreshConversations(),
      ]);
      const mapped = mapMessages(detail);
      // The stored history has no citations or tool traces, so attach this turn's from the stream.
      const lastAssistant = mapped.map((item) => item.role).lastIndexOf("assistant");
      if (lastAssistant >= 0) {
        mapped[lastAssistant] = {
          ...mapped[lastAssistant],
          citations: turn.citations,
          toolCalls: turn.toolCalls,
          grounding: turn.grounding,
          reasoning: turn.reasoning || null,
          usage: turn.usage ?? null,
        };
      }
      setMessages(mapped);
      setContext(detail.context ?? null);
      if (startedNewSession) record("Started a new session", "session");
    } catch (cause) {
      typer.cancel();
      if (stopRequested.current && runId.current === myRun) {
        const shown = revealed;
        if (!shown.trim()) {
          // Nothing was written yet, so the server kept nothing: hand the question back.
          setMessages((current) => current.filter((item) => !item.id.startsWith("pending-")));
          setComposerValue((current) => current || text);
        } else {
          // Keep exactly what the reader saw.
          const stamp = Date.now();
          setMessages((current) => [
            ...current.map((item) => (item.id.startsWith("pending-") ? { ...item, id: `stopped-user-${stamp}` } : item)),
            {
              id: `stopped-assistant-${stamp}`,
              role: "assistant",
              content: shown,
              model: null,
              created_at: new Date().toISOString(),
              citations: turn.citations,
              toolCalls: turn.toolCalls,
            },
          ]);
          void adoptSavedTurn();
        }
      } else {
        // The provider could not answer, but the question was sent: keep it in the transcript
        // and show the provider's reason as an assistant notice instead of a toast.
        const stamp = Date.now();
        const failure = cause instanceof Error ? cause.message : "Could not send message. Check your connection settings.";
        setMessages((current) => [
          ...current.map((item) => (item.id.startsWith("pending-") ? { ...item, id: `failed-user-${stamp}` } : item)),
          {
            id: `failed-assistant-${stamp}`,
            role: "assistant",
            content: failure,
            model: null,
            created_at: new Date().toISOString(),
            error: true,
          },
        ]);
      }
    } finally {
      if (runId.current === myRun) {
        abortRef.current = null;
        typerRef.current = null;
      }
      setLive(null);
      setComposerDisabled(false);
      window.setTimeout(focusComposer, 0);
    }
  }, [connection, activeId, messages, retrievalMode, documentScope, allowMutatingTools, reasoningEffort, refreshConversations, record]);

  // Stop writing the current answer. If the answer already finished and is only being typed
  // out, this skips the animation and shows the whole thing.
  const stopChat = useCallback(() => {
    stopRequested.current = true;
    abortRef.current?.abort();
    typerRef.current?.cancel();
  }, []);

  useEffect(() => {
    if (!composerDisabled || profileOpen || pendingDelete) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") stopChat();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [composerDisabled, profileOpen, pendingDelete, stopChat]);

  const handleUpload = useCallback(async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    try {
      await api("knowledge/documents/upload", connection, { method: "POST", body, timeoutMs: 120_000 });
      await refreshDocuments();
      record(`Uploaded ${file.name}`, "knowledge");
    } catch (cause) {
      setChatError(cause instanceof Error ? cause.message : "Upload failed.");
    }
  }, [connection, refreshDocuments, record]);

  const saveSettings = useCallback(async (next: Connection) => {
    persistConnection(next);
    setConnection(next);
    record("Updated connection settings", "settings");
  }, [record]);

  const removeApiKey = useCallback(() => {
    const next = { ...connection, apiKey: "" };
    persistConnection(next);
    setConnection(next);
    record("Removed the saved API key", "auth");
  }, [connection, record]);

  const signOut = useCallback(() => {
    void api("auth/logout", connection, { method: "POST" }).catch(() => undefined);
    const next = { ...connection, apiKey: "" };
    persistConnection(next);
    setConnection(next);
    setMe(null);
    setProfileOpen(false);
    setAuthState("required");
    setView("settings");
    record("Signed out", "auth");
  }, [connection, record]);

  const changeName = useCallback((name: string) => {
    const trimmed = name.trim();
    setCustomName(trimmed || null);
    saveProfileName(trimmed || null);
  }, []);

  const changeTheme = useCallback((next: Theme) => {
    setTheme(next);
    saveTheme(next);
  }, []);

  const userName = customName ?? (me ? nameFromUserId(me.user_id) : "Guest");
  const chooseStarter = (query: string) => {
    setComposerValue(query);
    window.setTimeout(focusComposer, 0);
  };

  const submitFeedback = useCallback(
    (messageId: string, rating: "up" | "down") => {
      if (!activeId) return;
      void api("chat/feedback", connection, {
        method: "POST",
        body: { conversation_id: activeId, message_id: messageId, rating },
      }).catch(() => undefined);
    },
    [activeId, connection],
  );

  if (authState === "required") {
    return <LoginScreen connection={connection} reason={authReason} />;
  }

  return (
    <div className={`app ${view === "chat" ? "" : "is-workspace"}`}>
      {view === "chat" && (
      <Sidebar
        open={sidebarOpen}
        hidden={sidebarHidden}
        onClose={() => setSidebarOpen(false)}
        onHide={() => setSidebarHidden(true)}
        conversations={conversations}
        loading={loadingConversations}
        error={conversationsError}
        activeId={activeId}
        onSelect={(id) => void selectConversation(id)}
        onNew={startNewSession}
        onDelete={setPendingDelete}
        onRetry={() => void refreshConversations()}
        view={view}
        onNavigate={navigate}
        check={check}
        userName={userName}
        onOpenProfile={() => setProfileOpen(true)}
        theme={theme}
        onToggleTheme={() => changeTheme(theme === "dark" ? "light" : "dark")}
      />
      )}
      <main ref={mainRef} onScroll={handleMainScroll} className={view === "chat" ? "" : "view-main"}>
        {view === "chat" && sidebarHidden && (
          <button
            type="button"
            className="sidebar-open-button"
            aria-label="Show navigation"
            onClick={() => setSidebarHidden(false)}
          >
            <SidebarToggle />
          </button>
        )}
        {view === "chat" && (
          <header className="mobile-topbar">
            <button className="icon-button" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="5" /><path d="M9 3v18" /></svg>
            </button>
          </header>
        )}

        {view === "chat" && (
          <>
            {messages.length > 0 ? (
              <div className="chat-area">
                <div className="messages">
                  {messages.map((message) => (
                    <div className={`message ${message.role === "user" ? "is-user" : ""}`} key={message.id}>
                      <ChatMessage
                        message={message}
                        onApprove={() => {
                          const target = approvalTarget(message, messages);
                          if (target) void runChat(target, true);
                        }}
                        onCancel={focusComposer}
                        onFeedback={submitFeedback}
                        actionPending={composerDisabled}
                        connection={connection}
                        onWidgetMessage={(text) => void runChat(text)}
                        onChooseOption={(text) => void runChat(text)}
                      />
                    </div>
                  ))}
                  {live && (live.text || live.reasoning ? (
                    <>
                      <div className="message" key="live">
                        <ChatMessage
                          streaming
                          message={{
                            id: "live",
                            role: "assistant",
                            content: live.text,
                            model: live.model,
                            created_at: "",
                            citations: live.citations,
                            toolCalls: live.toolCalls,
                            reasoning: live.reasoning || null,
                          }}
                          onApprove={() => {}}
                          onCancel={() => {}}
                          actionPending
                        />
                      </div>
                      {live.status && <PendingMessage status={live.status} />}
                    </>
                  ) : (
                    <PendingMessage status={live.status} />
                  ))}
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-logo"><VektorLogo size={110} /></div>
                <h1 className="empty-title">Hello! I&rsquo;m Vektor</h1>
                <p className="empty-sub">Your AI operations assistant for database and infrastructure.<br />How can I help you today?</p>
                <div className="starter-grid">
                  {STARTERS.map((starter) => (
                    <button className="starter-card" key={starter.title} onClick={() => chooseStarter(starter.query)}>
                      <span className="starter-icon-wrap" aria-hidden="true">{starter.icon}</span>
                      <div className="starter-copy">
                        <h2 className="starter-title">{starter.title}</h2>
                        <p className="starter-desc">{starter.desc}</p>
                      </div>
                      <ChevronRight size={16} className="starter-chevron" aria-hidden="true" />
                    </button>
                  ))}
                </div>
              </div>
            )}
            {chatError && (
              <div className="form-message error chat-error" role="alert">
                <div><strong>Something went wrong</strong><p>{chatError}</p></div>
                <button className="text-button" onClick={() => setChatError(null)}>Dismiss</button>
              </div>
            )}
            <Composer
              value={composerValue}
              onValueChange={setComposerValue}
              onSend={(value) => void runChat(value)}
              onUpload={handleUpload}
              disabled={composerDisabled}
              documents={documents}
              mode={retrievalMode}
              onModeChange={setRetrievalMode}
              scope={documentScope}
              onScopeChange={setDocumentScope}
              allowMutating={allowMutatingTools}
              onAllowMutatingChange={setAllowMutatingTools}
              reasoningEffort={reasoningEffort}
              onReasoningEffortChange={setReasoningEffort}
              onStop={stopChat}
              model={selectedModel || check.model}
              modelContextLength={modelContextLength}
              context={context}
              compacting={compacting}
              onCompact={() => void compactHistory()}
              connection={connection}
              activeProfileId={selectedProfileId}
              onSelectModel={(nextModel, nextProfileId, ctxLen) => {
                setSelectedModel(nextModel);
                setSelectedProfileId(nextProfileId);
                setModelContextLength(ctxLen ?? null);
              }}
              onOpenSettings={() => navigate("settings")}
            />
          </>
        )}

        {view !== "chat" && (
          <div className="crm-settings-shell">
            <aside className="crm-settings-rail" aria-label="Settings sections">
              <button
                type="button"
                className="crm-settings-back"
                onClick={() => navigate("chat")}
              >
                <ChevronRight size={15} className="crm-back-chevron" aria-hidden="true" />
                <span>Back to app</span>
              </button>

              <div className="crm-settings-group">
                <span className="crm-settings-eyebrow">Profile</span>
                <button
                  type="button"
                  className="crm-settings-profile"
                  onClick={() => setProfileOpen(true)}
                >
                  <span className="v-avatar" aria-hidden="true">{initials(userName)}</span>
                  <span className="crm-settings-profile-copy">
                    <strong>{userName}</strong>
                    <small>Open profile &amp; activity</small>
                  </span>
                  <ChevronRight size={15} aria-hidden="true" />
                </button>
              </div>

              <div className="crm-settings-group">
                <span className="crm-settings-eyebrow">App</span>
                <nav className="crm-settings-nav" aria-label="Settings navigation">
                <button
                  type="button"
                  className={`crm-settings-tab ${view === "settings" ? "is-active" : ""}`}
                  aria-current={view === "settings" ? "page" : undefined}
                  onClick={() => navigate("settings")}
                >
                  <Settings size={17} aria-hidden="true" />
                  <span>
                    <strong>Connection</strong>
                    <small>Providers, API key &amp; endpoint</small>
                  </span>
                </button>
                <button
                  type="button"
                  className={`crm-settings-tab ${view === "knowledge" ? "is-active" : ""}`}
                  aria-current={view === "knowledge" ? "page" : undefined}
                  onClick={() => navigate("knowledge")}
                >
                  <BookOpen size={17} aria-hidden="true" />
                  <span>
                    <strong>Knowledge Base</strong>
                    <small>Documents, upload &amp; search</small>
                  </span>
                </button>
                <button
                  type="button"
                  className={`crm-settings-tab ${view === "telemetry" ? "is-active" : ""}`}
                  aria-current={view === "telemetry" ? "page" : undefined}
                  onClick={() => navigate("telemetry")}
                >
                  <BarChart3 size={17} aria-hidden="true" />
                  <span>
                    <strong>Telemetry &amp; Analytics</strong>
                    <small>Token usage, models &amp; tools</small>
                  </span>
                </button>
                <button
                  type="button"
                  className={`crm-settings-tab ${view === "workflows" ? "is-active" : ""}`}
                  aria-current={view === "workflows" ? "page" : undefined}
                  onClick={() => navigate("workflows")}
                >
                  <Cpu size={17} aria-hidden="true" />
                  <span>
                    <strong>Workflows</strong>
                    <small>Pipelines &amp; approval gates</small>
                  </span>
                </button>
                </nav>
              </div>
            </aside>
            <div className="crm-settings-body">
              {view === "settings" && (
                <SettingsView
                  connection={connection}
                  onSave={saveSettings}
                  onTest={checkBackend}
                />
              )}
              {view === "knowledge" && (
                <KnowledgeView
                  connection={connection}
                  documents={documents}
                  loading={documentsLoading}
                  error={documentsError}
                  onRefresh={refreshDocuments}
                  onEvent={(label) => record(label, "knowledge")}
                  theme={theme}
                  onToggleTheme={() => changeTheme(theme === "dark" ? "light" : "dark")}
                />
              )}
              {view === "telemetry" && <TelemetryView connection={connection} />}
              {view === "workflows" && <WorkflowsView connection={connection} />}
            </div>
          </div>
        )}
      </main>

      {profileOpen && (
        <ProfileModal
          onClose={() => setProfileOpen(false)}
          me={me}
          name={userName}
          onNameChange={changeName}
          firstSeen={firstSeen}
          activity={activity}
          connection={connection}
          theme={theme}
          onThemeChange={changeTheme}
          onClearActivity={() => { localStorage.removeItem("vektor:activity"); setActivity([]); }}
          onClearKey={removeApiKey}
          onSignOut={signOut}
        />
      )}
      {pendingDelete && (
        <ConfirmDialog
          title="Delete this session?"
          description={`"${pendingDelete.title}" and all of its messages will be permanently removed.`}
          confirmLabel="Delete session"
          busy={deleting}
          onConfirm={() => void confirmDelete()}
          onClose={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
