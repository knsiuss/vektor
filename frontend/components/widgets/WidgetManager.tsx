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
    <div className="ops-stack">
      <form onSubmit={handleCreate} className="ops-card ops-stack">
        <strong style={{ fontSize: 14 }}>Buat Public Chatbot Widget</strong>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Nama widget (mis. Asisten Web Utama)"
          className="ops-input"
          required
        />
        <input
          value={domains}
          onChange={(e) => setDomains(e.target.value)}
          placeholder="Domain diizinkan, pisahkan koma (mis. domainku.com, *.domainku.com)"
          className="ops-input"
        />
        <input
          value={welcome}
          onChange={(e) => setWelcome(e.target.value)}
          placeholder="Pesan sambutan"
          className="ops-input"
        />
        <div>
          <button type="submit" disabled={saving} className="ops-btn">
            {saving ? "Menyimpan..." : "Buat Widget"}
          </button>
        </div>
      </form>

      {widgets.map((w) => {
        const snippet = `<script src="${typeof window !== "undefined" ? window.location.origin : ""}/widget.js" data-widget-key="${w.public_key}" async></script>`;
        return (
          <div key={w.id} className="ops-card ops-stack">
            <div className="ops-row">
              <strong>{w.name}</strong>
              <button type="button" onClick={() => void handleDelete(w.id)} className="ops-btn ops-btn-danger">
                Hapus
              </button>
            </div>
            <div className="ops-metric-label">
              Domains: {w.allowed_domains.length ? w.allowed_domains.join(", ") : "Semua domain"}
            </div>
            <pre className="ops-code">{snippet}</pre>
          </div>
        );
      })}
    </div>
  );
}
