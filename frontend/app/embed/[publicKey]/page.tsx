"use client";

import { useParams } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

interface WidgetConfig {
  name: string;
  welcome_message: string;
  theme: { primary_color?: string; position?: string };
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

function getVisitorToken(publicKey: string): string {
  const storageKey = `vektor_visitor_${publicKey}`;
  const existing = window.localStorage.getItem(storageKey);
  if (existing) return existing;
  const created = `vis_${crypto.randomUUID().replace(/-/g, "")}`;
  window.localStorage.setItem(storageKey, created);
  return created;
}

export default function EmbedWidgetPage() {
  const params = useParams<{ publicKey: string }>();
  const publicKey = params.publicKey;
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!publicKey) return;
    fetch(`${API_BASE}/api/v1/public/widgets/${encodeURIComponent(publicKey)}/config`)
      .then(async (res) => {
        if (!res.ok) throw new Error("Widget unavailable");
        return (await res.json()) as WidgetConfig;
      })
      .then((data) => {
        setConfig(data);
        setMessages([{ id: "welcome", role: "assistant", content: data.welcome_message }]);
      })
      .catch(() => setError("Widget tidak tersedia atau domain tidak diizinkan."));
  }, [publicKey]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading || !publicKey) return;

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: text };
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, userMsg, { id: assistantId, role: "assistant", content: "" }]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(
        `${API_BASE}/api/v1/public/widgets/${encodeURIComponent(publicKey)}/chat/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, visitor_token: getVisitorToken(publicKey) }),
        },
      );
      if (!res.ok || !res.body) throw new Error("Failed to send message");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw || raw === "[DONE]") continue;
          try {
            const evt = JSON.parse(raw) as { delta?: string; content?: string };
            const chunk = evt.delta ?? evt.content ?? "";
            if (chunk) {
              setMessages((prev) =>
                prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + chunk } : m)),
              );
            }
          } catch {
            // Ignore non-JSON SSE frames
          }
        }
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: "Maaf, terjadi gangguan. Silakan coba lagi." } : m,
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  if (error) {
    return <div className="flex h-screen items-center justify-center p-4 text-sm text-red-600">{error}</div>;
  }

  const primaryColor = config?.theme?.primary_color ?? "#2563eb";

  return (
    <div className="flex h-screen flex-col bg-white text-slate-900">
      <header className="px-4 py-3 text-sm font-semibold text-white" style={{ backgroundColor: primaryColor }}>
        {config?.name ?? "Assistant"}
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[82%] rounded-2xl px-3.5 py-2 whitespace-pre-wrap ${
                m.role === "user" ? "text-white" : "bg-slate-100 text-slate-900"
              }`}
              style={m.role === "user" ? { backgroundColor: primaryColor } : undefined}
            >
              {m.content || "..."}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-slate-200 p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Tulis pertanyaan..."
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          style={{ backgroundColor: primaryColor }}
        >
          Kirim
        </button>
      </form>
    </div>
  );
}
