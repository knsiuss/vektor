"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type ChannelType = "telegram" | "whatsapp_cloud" | "whatsapp_qr" | "discord";

interface ChannelItem {
  id: string;
  channel_type: ChannelType;
  name: string;
  webhook_path: string;
  has_credentials: boolean;
  is_active: boolean;
}

const TEMPLATES: Record<
  ChannelType,
  { label: string; hint: string; fields: Array<{ key: string; label: string; secret?: boolean }> }
> = {
  telegram: {
    label: "Telegram Bot",
    hint: "Buat bot di @BotFather, tempel token di bawah, lalu arahkan setWebhook ke URL yang muncul.",
    fields: [{ key: "bot_token", label: "Bot Token (@BotFather)", secret: true }],
  },
  whatsapp_cloud: {
    label: "WhatsApp Cloud API",
    hint: "Masukkan Phone Number ID & Access Token dari Meta Developers, lalu tempel Webhook URL.",
    fields: [
      { key: "phone_number_id", label: "Phone Number ID" },
      { key: "access_token", label: "Permanent Access Token", secret: true },
      { key: "verify_token", label: "Verify Token" },
    ],
  },
  whatsapp_qr: {
    label: "WhatsApp Scan QR",
    hint: "Hubungkan ke bridge WAHA/Evolution, scan QR di bridge, lalu arahkan webhook ke URL ini.",
    fields: [
      { key: "bridge_url", label: "Bridge URL (mis. http://localhost:3001)" },
      { key: "api_key", label: "Bridge API Key (opsional)", secret: true },
    ],
  },
  discord: {
    label: "Discord Bot",
    hint: "Tempel Interactions Endpoint URL di Discord Developer Portal untuk slash command.",
    fields: [{ key: "public_key", label: "Discord Application Public Key" }],
  },
};

export function ChannelManager() {
  const [channels, setChannels] = useState<ChannelItem[]>([]);
  const [type, setType] = useState<ChannelType>("telegram");
  const [name, setName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [publicUrl, setPublicUrl] = useState("");
  const [setupMsg, setSetupMsg] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const res = await fetch("/api/v1/channels");
    if (res.ok) setChannels((await res.json()) as ChannelItem[]);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      const res = await fetch("/api/v1/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel_type: type,
          name: name.trim(),
          system_prompt: systemPrompt.trim() || null,
          config,
        }),
      });
      if (res.ok) {
        setName("");
        setSystemPrompt("");
        setConfig({});
        await load();
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    const res = await fetch(`/api/v1/channels/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (res.ok) await load();
  }

  async function handleTelegramSetup(id: string) {
    const base = publicUrl.trim() || (typeof window !== "undefined" ? window.location.origin : "");
    if (!base) return;
    setSetupMsg((prev) => ({ ...prev, [id]: "Menghubungkan..." }));
    const res = await fetch(`/api/v1/channels/${encodeURIComponent(id)}/telegram/setup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ public_base_url: base }),
    });
    setSetupMsg((prev) => ({
      ...prev,
      [id]: res.ok ? "Webhook Telegram aktif ✓" : "Gagal setup (pastikan URL publik HTTPS & token valid)",
    }));
  }

  const template = TEMPLATES[type];

  return (
    <div className="ops-stack">
      <div className="ops-grid-4" style={{ marginBottom: 4 }}>
        {(Object.keys(TEMPLATES) as ChannelType[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setType(key);
              setConfig({});
            }}
            className={`ops-tab ${type === key ? "is-active" : ""}`}
          >
            {TEMPLATES[key].label}
          </button>
        ))}
      </div>

      <form onSubmit={handleCreate} className="ops-card ops-stack">
        <div>
          <strong style={{ fontSize: 14 }}>{template.label}</strong>
          <p className="ops-metric-label" style={{ margin: "4px 0 0" }}>{template.hint}</p>
        </div>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Nama bot (mis. Asisten Layanan Pelanggan)"
          className="ops-input"
          required
        />
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder="Persona / System Prompt khusus bot (opsional)"
          rows={2}
          className="ops-input"
        />
        {template.fields.map((f) => (
          <input
            key={f.key}
            type={f.secret ? "password" : "text"}
            value={config[f.key] ?? ""}
            onChange={(e) => setConfig((prev) => ({ ...prev, [f.key]: e.target.value }))}
            placeholder={f.label}
            className="ops-input"
          />
        ))}
        <div>
          <button type="submit" disabled={saving} className="ops-btn">
            {saving ? "Menyimpan..." : "Buat Connector"}
          </button>
        </div>
      </form>

      {channels.map((c) => {
        const fullUrl = `${typeof window !== "undefined" ? window.location.origin : ""}${c.webhook_path}`;
        return (
          <div key={c.id} className="ops-card ops-stack">
            <div className="ops-row">
              <strong>
                {c.name}{" "}
                <span className="ops-metric-label">({c.channel_type})</span>
              </strong>
              <button type="button" onClick={() => void handleDelete(c.id)} className="ops-btn ops-btn-danger">
                Hapus
              </button>
            </div>
            <div className="ops-metric-label">Webhook URL:</div>
            <pre className="ops-code">{fullUrl}</pre>
            {c.channel_type === "telegram" && (
              <div className="ops-row">
                <input
                  value={publicUrl}
                  onChange={(e) => setPublicUrl(e.target.value)}
                  placeholder="Public HTTPS URL (mis. https://api.domainmu.com)"
                  className="ops-input"
                />
                <button
                  type="button"
                  onClick={() => void handleTelegramSetup(c.id)}
                  className="ops-btn ops-btn-ghost"
                  style={{ whiteSpace: "nowrap" }}
                >
                  Auto-Setup Webhook
                </button>
              </div>
            )}
            {setupMsg[c.id] && <div className="ops-metric-label">{setupMsg[c.id]}</div>}
          </div>
        );
      })}
    </div>
  );
}
