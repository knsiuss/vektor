"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

interface InboxSession {
  id: string;
  connector_id: string;
  external_user_id: string;
  conversation_id: string;
  handover_mode: boolean;
  unknown_streak: number;
  assigned_agent_id: string | null;
  last_active_at: string;
}

interface InboxMessage {
  id: string;
  role: string;
  content: string;
  provider: string | null;
  created_at: string;
}

export function UnifiedInbox() {
  const [sessions, setSessions] = useState<InboxSession[]>([]);
  const [selected, setSelected] = useState<InboxSession | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const [promotedId, setPromotedId] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    const res = await fetch("/api/v1/inbox/sessions");
    if (res.ok) {
      const list = (await res.json()) as InboxSession[];
      setSessions(list);
      setSelected((prev) => (prev ? list.find((s) => s.id === prev.id) ?? list[0] ?? null : list[0] ?? null));
    }
  }, []);

  const loadMessages = useCallback(async (sessionId: string) => {
    const res = await fetch(`/api/v1/inbox/sessions/${encodeURIComponent(sessionId)}/messages`);
    if (res.ok) setMessages((await res.json()) as InboxMessage[]);
  }, []);

  useEffect(() => {
    void loadSessions();
    const es = new EventSource("/api/v1/inbox/stream");
    const refresh = () => {
      void loadSessions();
      if (selected) void loadMessages(selected.id);
    };
    es.addEventListener("inbox.message", refresh);
    es.addEventListener("inbox.assigned", refresh);
    return () => es.close();
  }, [loadSessions, loadMessages, selected]);

  useEffect(() => {
    if (selected) void loadMessages(selected.id);
    else setMessages([]);
  }, [selected, loadMessages]);

  async function assignToMe(item: InboxSession) {
    const res = await fetch(`/api/v1/inbox/sessions/${encodeURIComponent(item.id)}/assign`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (res.ok) await loadSessions();
  }

  async function toggleHandover(item: InboxSession) {
    const res = await fetch(`/api/v1/inbox/sessions/${encodeURIComponent(item.id)}/handover`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ handover_mode: !item.handover_mode }),
    });
    if (res.ok) await loadSessions();
  }

  async function promoteToKB(messageId: string) {
    if (!selected) return;
    const res = await fetch(
      `/api/v1/inbox/sessions/${encodeURIComponent(selected.id)}/messages/${encodeURIComponent(messageId)}/promote-kb`,
      { method: "POST" },
    );
    if (res.ok) setPromotedId(messageId);
  }

  async function handleReply(e: FormEvent) {
    e.preventDefault();
    if (!selected || !replyText.trim() || sending) return;
    setSending(true);
    try {
      const res = await fetch(`/api/v1/inbox/sessions/${encodeURIComponent(selected.id)}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: replyText.trim() }),
      });
      if (res.ok) {
        setReplyText("");
        await loadMessages(selected.id);
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="ops-inbox-grid">
      <div className="ops-stack">
        {sessions.length === 0 && (
          <div className="ops-card ops-metric-label">Belum ada percakapan channel yang masuk.</div>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSelected(s)}
            className={`ops-tab ${selected?.id === s.id ? "is-active" : ""}`}
          >
            <div style={{ fontWeight: 600 }}>{s.external_user_id}</div>
            <div className="ops-metric-label" style={{ marginTop: 4 }}>
              {s.handover_mode ? "Human Handover" : "AI Auto-Reply"}
            </div>
          </button>
        ))}
      </div>

      <div className="ops-chat-box">
        {selected ? (
          <>
            <div className="ops-row" style={{ padding: "12px 16px", borderBottom: "1px solid var(--color-border)" }}>
              <div>
                <strong style={{ fontSize: 14 }}>{selected.external_user_id}</strong>
                {selected.assigned_agent_id && (
                  <span className="ops-metric-label" style={{ marginLeft: 8 }}>
                    Agent: {selected.assigned_agent_id}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" onClick={() => void assignToMe(selected)} className="ops-btn ops-btn-ghost">
                  Assign to Me
                </button>
                <button type="button" onClick={() => void toggleHandover(selected)} className="ops-btn">
                  {selected.handover_mode ? "Kembalikan ke AI" : "Take Over"}
                </button>
              </div>
            </div>
            <div className="ops-chat-messages">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`ops-bubble ${m.role === "user" ? "ops-bubble-user" : "ops-bubble-agent"}`}
                >
                  {m.content}
                  {m.provider === "human" && (
                    <div style={{ marginTop: 6, textAlign: "right" }}>
                      <button
                        type="button"
                        onClick={() => void promoteToKB(m.id)}
                        style={{ background: "none", border: "none", color: "inherit", textDecoration: "underline", fontSize: 11, cursor: "pointer" }}
                      >
                        {promotedId === m.id ? "Tersimpan ke KB ✓" : "Simpan ke KB"}
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <form
              onSubmit={handleReply}
              className="ops-row"
              style={{ padding: 12, borderTop: "1px solid var(--color-border)" }}
            >
              <input
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                placeholder="Ketik balasan manual ke customer..."
                className="ops-input"
                disabled={sending}
              />
              <button type="submit" disabled={sending || !replyText.trim()} className="ops-btn">
                Kirim
              </button>
            </form>
          </>
        ) : (
          <div className="ops-metric-label" style={{ margin: "auto" }}>
            Pilih percakapan untuk melihat riwayat dan membalas.
          </div>
        )}
      </div>
    </div>
  );
}
