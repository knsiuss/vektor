"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Connection, ProviderName, ProviderProfile } from "@/lib/types";

import { LoaderCircle, Plus, Trash2 } from "./icons";

export function ProviderProfilesCard({
  connection,
  refreshSignal = 0,
}: {
  connection: Connection;
  refreshSignal?: number;
}) {
  const [profiles, setProfiles] = useState<ProviderProfile[]>([]);
  const [label, setLabel] = useState("");
  const [provider, setProvider] = useState<ProviderName>("openrouter");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api<ProviderProfile[]>("providers/profiles", connection);
      setProfiles(list);
    } catch {
      setProfiles([]);
    }
  }, [connection]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshSignal]);

  async function addProfile(event: React.FormEvent) {
    event.preventDefault();
    if (!label.trim() || !model.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api<ProviderProfile>("providers/profiles", connection, {
        method: "POST",
        body: {
          label: label.trim(),
          provider,
          model: model.trim(),
          base_url: baseUrl.trim() || null,
          api_key: apiKey.trim() || null,
          is_default: false,
        },
      });
      setLabel("");
      setApiKey("");
      setBaseUrl("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save API profile.");
    } finally {
      setBusy(false);
    }
  }

  async function removeProfile(id: string) {
    setBusy(true);
    try {
      await api<void>(`providers/profiles/${id}`, connection, { method: "DELETE" });
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="profiles-card">
      <div className="profiles-head">
        <h3>Additional APIs &amp; Keys ({profiles.length})</h3>
        <p>Save multiple provider APIs so you can switch models across providers directly in chat.</p>
      </div>
      {error && <div className="form-message error"><p>{error}</p></div>}

      <form className="profiles-form" onSubmit={(e) => void addProfile(e)}>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Label (e.g. OpenAI Work)"
          required
        />
        <select value={provider} onChange={(e) => setProvider(e.target.value as ProviderName)}>
          <option value="openrouter">OpenRouter</option>
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="google">Google</option>
          <option value="custom">Custom</option>
        </select>
        <input
          type="text"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="Default model ID"
          required
        />
        <input
          type="url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="Base URL (optional)"
        />
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="API Key"
        />
        <button type="submit" className="button" disabled={busy}>
          {busy ? <LoaderCircle size={14} className="spin" /> : <Plus size={14} />}
          Add API
        </button>
      </form>

      {profiles.length > 0 && (
        <div className="profiles-list">
          {profiles.map((p) => (
            <div className="profiles-row" key={p.id}>
              <div>
                <strong>{p.label}</strong>{" "}
                <span className="profiles-meta">
                  {p.provider} &middot; {p.model}
                  {p.api_key_configured ? " · Key saved" : ""}
                </span>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label={`Delete ${p.label}`}
                onClick={() => void removeProfile(p.id)}
                disabled={busy}
              >
                <Trash2 size={15} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
