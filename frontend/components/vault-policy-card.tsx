"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Connection } from "@/lib/types";

import { LoaderCircle, Plus, ShieldCheck, Trash2 } from "./icons";

type VaultKey = {
  id: string;
  provider: string;
  label: string;
  last4: string;
  base_url: string | null;
  status: string;
};

type TenantPolicy = {
  tenant_id: string;
  key_mode: "byok" | "managed";
  daily_cap_usd: number | null;
  fallback_to_credits: boolean;
};

type CreditBalance = {
  balance_micros: number;
  balance_usd: number;
};

export function VaultPolicyCard({ connection }: { connection: Connection }) {
  const [keys, setKeys] = useState<VaultKey[]>([]);
  const [policy, setPolicy] = useState<TenantPolicy | null>(null);
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [provider, setProvider] = useState("openrouter");
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    try {
      const [k, p, b] = await Promise.all([
        api<VaultKey[]>("keys", connection),
        api<TenantPolicy>("tenant/policy", connection),
        api<CreditBalance>("credits/balance", connection),
      ]);
      setKeys(k);
      setPolicy(p);
      setBalance(b);
    } catch {
      // Unconfigured or offline backend: keep card quiet until connected.
    }
  }, [connection]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function savePolicy(patch: Partial<TenantPolicy>) {
    if (!policy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api<TenantPolicy>("tenant/policy", connection, {
        method: "PUT",
        body: { ...policy, ...patch },
      });
      setPolicy(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to update policy.");
    } finally {
      setBusy(false);
    }
  }

  async function addKey(event: React.FormEvent) {
    event.preventDefault();
    if (!apiKey.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api<VaultKey>("keys", connection, {
        method: "POST",
        body: {
          provider,
          label: label.trim() || "Default",
          api_key: apiKey.trim(),
          base_url: baseUrl.trim() || null,
        },
      });
      setLabel("");
      setApiKey("");
      setBaseUrl("");
      await loadAll();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add key to vault.");
    } finally {
      setBusy(false);
    }
  }

  async function removeKey(id: string) {
    setBusy(true);
    try {
      await api<void>(`keys/${id}`, connection, { method: "DELETE" });
      await loadAll();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="profiles-card">
      <div className="profiles-head">
        <h3><ShieldCheck size={15} aria-hidden="true" /> Encrypted Key Vault &amp; Tenant Policy</h3>
        <p>
          Mode:{" "}
          <strong>{policy?.key_mode === "managed" ? "Managed Credits" : "BYOK"}</strong>
          {balance ? ` · Balance: $${balance.balance_usd.toFixed(4)}` : ""}
        </p>
      </div>

      {error && <div className="form-message error"><p>{error}</p></div>}

      {policy && (
        <div className="profiles-form">
          <select
            value={policy.key_mode}
            disabled={busy}
            onChange={(e) =>
              void savePolicy({ key_mode: e.target.value as "byok" | "managed" })
            }
          >
            <option value="byok">BYOK (Use my own encrypted keys)</option>
            <option value="managed">Managed (Use platform credit ledger)</option>
          </select>
          <label className="wf-input-inline">
            <input
              type="checkbox"
              checked={policy.fallback_to_credits}
              disabled={busy}
              onChange={(e) => void savePolicy({ fallback_to_credits: e.target.checked })}
            />
            <span>Opt-in fallback to credits on BYOK error</span>
          </label>
        </div>
      )}

      <form className="profiles-form" onSubmit={(e) => void addKey(e)}>
        <select value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="openrouter">OpenRouter</option>
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="google">Google</option>
          <option value="custom">Custom</option>
        </select>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Key label"
        />
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-..."
          required
        />
        <input
          type="url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="Custom HTTPS base URL (anti-SSRF)"
        />
        <button type="submit" className="button" disabled={busy}>
          {busy ? <LoaderCircle size={14} className="spin" /> : <Plus size={14} />}
          Store in Vault
        </button>
      </form>

      {keys.length > 0 && (
        <div className="profiles-list">
          {keys.map((k) => (
            <div className="profiles-row" key={k.id}>
              <div>
                <strong>{k.label}</strong>{" "}
                <span className="profiles-meta">
                  {k.provider} &middot; &bull;&bull;&bull;&bull;{k.last4} &middot; {k.status}
                </span>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label={`Delete key ${k.label}`}
                onClick={() => void removeKey(k.id)}
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
