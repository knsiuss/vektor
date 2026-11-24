"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

interface WidgetItem {
  id: string;
  public_key: string;
  name: string;
  allowed_domains: string[];
  welcome_message: string;
  is_active: boolean;
}

export function WidgetManager() {
  const [widgets, setWidgets] = useState<WidgetItem[]>([]);
  const [name, setName] = useState("");
  const [domains, setDomains] = useState("");
  const [welcome, setWelcome] = useState("Halo! Ada yang bisa saya bantu?");
  const [saving, setSaving] = useState(false);

  const loadWidgets = useCallback(async () => {
    const res = await fetch("/api/v1/widgets");
    if (res.ok) setWidgets((await res.json()) as WidgetItem[]);
  }, []);

  useEffect(() => {
    void loadWidgets();
  }, [loadWidgets]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      const allowed_domains = domains
        .split(",")
        .map((d) => d.trim())
        .filter(Boolean);
      const res = await fetch("/api/v1/widgets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), allowed_domains, welcome_message: welcome.trim() }),
      });
      if (res.ok) {
        setName("");
        setDomains("");
        await loadWidgets();
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    const res = await fetch(`/api/v1/widgets/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (res.ok) await loadWidgets();
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleCreate} className="space-y-3 rounded-xl border border-slate-200 p-4">
        <h2 className="text-base font-semibold">Buat Public Chatbot Widget</h2>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Nama widget (mis. CS Toko Utama)"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          required
        />
        <input
          value={domains}
          onChange={(e) => setDomains(e.target.value)}
          placeholder="Domain diizinkan, pisahkan koma (mis. tokoku.com, *.tokoku.com)"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <input
          value={welcome}
          onChange={(e) => setWelcome(e.target.value)}
          placeholder="Pesan sambutan"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? "Menyimpan..." : "Buat Widget"}
        </button>
      </form>

      <div className="space-y-3">
        {widgets.map((w) => {
          const snippet = `<script src="${typeof window !== "undefined" ? window.location.origin : ""}/widget.js" data-widget-key="${w.public_key}" async></script>`;
          return (
            <div key={w.id} className="space-y-2 rounded-xl border border-slate-200 p-4 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-semibold">{w.name}</span>
                <button
                  type="button"
                  onClick={() => void handleDelete(w.id)}
                  className="text-xs text-red-600 hover:underline"
                >
                  Hapus
                </button>
              </div>
              <div className="text-xs text-slate-500">
                Domains: {w.allowed_domains.length ? w.allowed_domains.join(", ") : "Semua domain"}
              </div>
              <pre className="overflow-x-auto rounded bg-slate-100 p-2 text-xs">{snippet}</pre>
            </div>
          );
        })}
      </div>
    </div>
  );
}
