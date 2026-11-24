"use client";

import { useEffect, useState } from "react";

import type {
  Connection,
  ConnectionCheckResult,
  ProviderName,
  ProviderSetting,
  ProviderSettingIn,
} from "@/lib/types";
import {
  clearProviderApiKey,
  getProviderSettings,
  testProviderConnection,
  upsertProviderSettings,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { FALLBACK_MODELS } from "@/lib/models";
import { ModelPicker } from "./model-picker";
import {
  Check,
  ChevronDown,
  Clock,
  Cpu,
  Eye,
  EyeOff,
  Gauge,
  Info,
  LinkIcon,
  LoaderCircle,
  RefreshCw,
  Save,
  Server,
  Settings,
  ShieldCheck,
} from "./icons";

export const DEFAULT_CONNECTION: Connection = {
  baseUrl: "http://127.0.0.1:8000",
  apiKey: "",
  timeoutSeconds: 30,
  maxRetries: 3,
  extraHeaders: "",
};

const PROVIDERS: { id: ProviderName; label: string; subtitle: string }[] = [
  { id: "openai", label: "OpenAI", subtitle: "ChatGPT" },
  { id: "anthropic", label: "Anthropic", subtitle: "Claude" },
  { id: "google", label: "Google", subtitle: "Gemini" },
  { id: "openrouter", label: "OpenRouter", subtitle: "Aggregator" },
  { id: "mistral", label: "Mistral", subtitle: "Mistral AI" },
  { id: "deepseek", label: "DeepSeek", subtitle: "DeepSeek" },
  { id: "qwen", label: "Qwen", subtitle: "Alibaba" },
  { id: "custom", label: "Other", subtitle: "OpenAI-compatible" },
];

function modelForProvider(provider: ProviderName): string {
  return FALLBACK_MODELS[provider]?.[0] ?? "";
}

type Draft = {
  provider: ProviderName;
  model: string;
  apiKey: string;
  baseUrl: string;
};

function toDraft(setting: ProviderSetting): Draft {
  return {
    provider: (setting.provider as ProviderName) ?? "openai",
    model: setting.model ?? modelForProvider("openai"),
    apiKey: "",
    baseUrl: setting.base_url ?? "",
  };
}

const EMPTY_SETTING: ProviderSetting = {
  provider: "openai",
  model: null,
  api_key_configured: false,
  base_url: null,
  connection_status: "disconnected",
  connection_error: null,
  last_checked_at: null,
  latency_ms: null,
};

function providerIcon(provider: ProviderName) {
  if (provider === "openai") return <Settings size={18} />;
  if (provider === "anthropic") return <Cpu size={18} />;
  if (provider === "google") return <ShieldCheck size={18} />;
  if (provider === "openrouter") return <LinkIcon size={18} />;
  if (provider === "custom") return <Server size={18} />;
  return <Cpu size={18} />;
}

const PROVIDER_LABELS: Record<ProviderName, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  openrouter: "OpenRouter",
  mistral: "Mistral",
  deepseek: "DeepSeek",
  qwen: "Qwen",
  custom: "Other",
};

export function SettingsView({
  connection,
  onSave,
  onTest,
}: {
  connection: Connection;
  onSave: (connection: Connection) => Promise<void>;
  onTest: (connection: Connection) => Promise<{ status: string; latencyMs: number | null; model: string | null; error: string | null }>;
}) {
  const [setting, setSetting] = useState<ProviderSetting | null>(null);
  const [draft, setDraft] = useState<Draft>({
    provider: "openai",
    model: modelForProvider("openai"),
    apiKey: "",
    baseUrl: "",
  });
  const [showKey, setShowKey] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ url: string; result: ConnectionCheckResult } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const loaded = await getProviderSettings(connection);
        if (!cancelled) setSetting(loaded);
      } catch {
        if (!cancelled) setSetting(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [connection]);

  useEffect(() => {
    if (setting) {
      setDraft(toDraft(setting));
    }
  }, [setting]);

  function change(patch: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...patch }));
    setSaved(false);
  }

  function buildPayload(): ProviderSettingIn {
    return {
      provider: draft.provider,
      model: draft.model || null,
      api_key: draft.apiKey || null,
      base_url: draft.baseUrl || null,
    };
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      await upsertProviderSettings(connection, buildPayload());
      setSaved(true);
      await onSave(connection);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save provider settings.");
      setSaved(false);
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setError("");
    setTesting(true);
    try {
      const result = await testProviderConnection(connection, buildPayload());
      setTestResult({ url: draft.baseUrl || "", result });
    } catch (cause) {
      setTestResult({
        url: draft.baseUrl || "",
        result: {
          status: "disconnected",
          latency_ms: null,
          model: null,
          error: cause instanceof Error ? cause.message : "Connection test failed.",
        },
      });
    } finally {
      setTesting(false);
    }
  }

  async function clearKey() {
    try {
      await clearProviderApiKey(connection);
      setDraft((current) => ({ ...current, apiKey: "" }));
      setSaved(false);
    } catch {
      // Ignore: having no key configured is not an error for the user.
    }
  }

  function resetToDefault() {
    setDraft({
      provider: "openai",
      model: modelForProvider("openai"),
      apiKey: "",
      baseUrl: "",
    });
    setError("");
    setSaved(false);
  }

  function cancel() {
    setDraft(setting ? toDraft(setting) : { provider: "openai", model: modelForProvider("openai"), apiKey: "", baseUrl: "" });
    setError("");
    setSaved(false);
  }

  const baseShown = setting ?? EMPTY_SETTING;
  const testShown = testResult?.result;
  const shown = {
    provider: baseShown.provider,
    model: testShown?.model ?? baseShown.model,
    api_key_configured: baseShown.api_key_configured,
    base_url: baseShown.base_url,
    connection_status: testShown?.status ?? baseShown.connection_status,
    connection_error: testShown?.error ?? baseShown.connection_error,
    last_checked_at: baseShown.last_checked_at,
    latency_ms: testShown?.latency_ms ?? baseShown.latency_ms,
  };
  const busy = testing || shown.connection_status === "checking";
  const connected = shown.connection_status === "connected";
  const heading = busy ? "Checking" : connected ? "Connected" : "Not connected";
  const detail = busy
    ? "Contacting the AI provider."
    : connected
      ? "Vektor is ready to use."
      : shown.connection_error ?? "The provider could not be reached.";
  const statusClass = busy ? "checking" : shown.connection_status;
  const isDefaultModel = draft.model === modelForProvider(draft.provider);

  return (
    <section className="view v-settings" aria-labelledby="settings-title">
      <header className="view-header">
        <div className="v-title-row">
          <span className="v-title-icon" aria-hidden="true"><Settings size={22} /></span>
          <div>
            <h1 id="settings-title">Connection Settings</h1>
            <p>Configure your AI provider and connection details.</p>
          </div>
        </div>
        <button type="button" className="button secondary v-with-icon" onClick={resetToDefault}>
          <RefreshCw size={16} aria-hidden="true" />Reset to Default
        </button>
      </header>

      <form className="v-settings-form" noValidate onSubmit={(event) => void save(event)}>
        <div className="v-settings-grid">
          <div className="v-settings-main">
            <section className="v-card" aria-labelledby="provider-title">
              <h2 id="provider-title">AI Provider</h2>
              <p className="v-card-sub">Choose which provider you want to use for Vektor.</p>

              <div className="v-provider-cards" role="group" aria-labelledby="provider-title">
                {PROVIDERS.map((provider) => {
                  const selected = draft.provider === provider.id;
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      className={`v-provider-card ${selected ? "is-selected" : ""}`}
                      onClick={() => change({ provider: provider.id, model: modelForProvider(provider.id) })}
                      aria-pressed={selected}
                    >
                      {selected && <span className="v-provider-dot" aria-hidden="true" />}
                      <span className="v-provider-icon" aria-hidden="true">{providerIcon(provider.id)}</span>
                      <span className="v-provider-info">
                        <strong>{provider.label}</strong>
                        <span>{provider.subtitle}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="v-card" aria-labelledby="config-title">
              <h2 id="config-title">Provider Configuration</h2>

              <div className="v-field">
                <div className="v-field-head">
                  <label htmlFor="provider-model">Model</label>
                  {isDefaultModel && <span className="v-badge-rec">Recommended</span>}
                </div>
                <ModelPicker
                  connection={connection}
                  provider={draft.provider}
                  baseUrl={draft.baseUrl}
                  apiKey={draft.apiKey}
                  value={draft.model}
                  onChange={(model) => change({ model })}
                />
              </div>

              <div className="v-field">
                <div className="v-field-head">
                  <label htmlFor="provider-api-key">API Key</label>
                </div>
                <div className="v-input-wrap">
                  <input
                    id="provider-api-key"
                    name="provider-api-key"
                    type={showKey ? "text" : "password"}
                    value={draft.apiKey}
                    onChange={(event) => change({ apiKey: event.target.value })}
                    placeholder={shown.api_key_configured ? "•••••••••••• (saved)" : "sk-..."}
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    className="v-eye"
                    onClick={() => setShowKey((value) => !value)}
                    aria-label={showKey ? "Hide API key" : "Show API key"}
                    aria-pressed={showKey}
                  >
                    {showKey ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
                  </button>
                </div>
                <p className="v-info-line">
                  <Info size={13} aria-hidden="true" />
                  Stored on the Vektor server and never returned by the API.
                </p>
                {setting?.api_key_configured && (
                  <button type="button" className="v-clear-key" onClick={() => void clearKey()}>
                    Remove saved key
                  </button>
                )}
              </div>

              <div className="v-divider" />

              <button
                type="button"
                className="v-advanced-toggle"
                aria-expanded={advanced}
                aria-controls="advanced-body"
                onClick={() => setAdvanced((value) => !value)}
              >
                Advanced Options
                <ChevronDown size={15} className={advanced ? "is-open" : ""} aria-hidden="true" />
              </button>
              {(advanced || draft.provider === "custom") && (
                <div className="v-advanced-body" id="advanced-body">
                  <div className="v-field">
                    <label htmlFor="provider-base-url">
                      {draft.provider === "custom" ? "API Base URL" : "Base URL (Optional)"}
                    </label>
                    <div className="v-input-wrap">
                      <LinkIcon size={16} aria-hidden="true" />
                      <input
                        id="provider-base-url"
                        name="provider-base-url"
                        type="text"
                        inputMode="url"
                        value={draft.baseUrl}
                        onChange={(event) => change({ baseUrl: event.target.value })}
                        placeholder="https://api.example.com/v1"
                        autoComplete="url"
                      />
                    </div>
                    <p className="v-hint">
                      {draft.provider === "custom"
                        ? "Point this at any OpenAI-compatible API (Mistral, DeepSeek, Qwen, vLLM…), then load its models."
                        : "Override the provider endpoint only if you use a proxy or self-hosted gateway."}
                    </p>
                  </div>
                </div>
              )}

              {error && (
                <div className="form-message error" role="alert">
                  <div><strong>Settings not saved</strong><p>{error}</p></div>
                </div>
              )}
              {saved && (
                <div className="form-message success" role="status">
                  <Check size={18} aria-hidden="true" />
                  <div><strong>Settings saved</strong><p>The provider configuration was saved.</p></div>
                </div>
              )}
            </section>
          </div>

          <aside className="v-side">
            <section className="v-card" aria-labelledby="status-title" aria-live="polite">
              <div className="v-card-head">
                <h2 id="status-title">Connection Status</h2>
                <span className={`status-dot ${statusClass}`} aria-hidden="true" />
              </div>
              <div className={`v-status-hero ${statusClass}`}>
                <span className="v-status-badge" aria-hidden="true">
                  {busy ? <LoaderCircle className="spin" size={24} /> : connected ? <Check size={26} /> : "!"}
                </span>
                <div>
                  <strong>{heading}</strong>
                  <p>{detail}</p>
                </div>
              </div>

              <dl className="v-facts">
                <div><dt><Server size={15} aria-hidden="true" />Provider</dt><dd>{PROVIDER_LABELS[shown.provider] ?? shown.provider}</dd></div>
                <div><dt><Cpu size={15} aria-hidden="true" />Model</dt><dd>{shown.model ?? "Not set"}</dd></div>
                <div><dt><LinkIcon size={15} aria-hidden="true" />Base URL</dt><dd>{shown.base_url ?? "Default endpoint"}</dd></div>
                <div><dt><Gauge size={15} aria-hidden="true" />Latency</dt><dd>{shown.latency_ms === null ? "—" : `${shown.latency_ms}ms`}</dd></div>
                <div>
                  <dt><ShieldCheck size={15} aria-hidden="true" />Auth</dt>
                  <dd>{shown.api_key_configured ? "API key saved" : "No API key"}</dd>
                </div>
                <div>
                  <dt><Clock size={15} aria-hidden="true" />Last Checked</dt>
                  <dd>{shown.last_checked_at ? formatDateTime(shown.last_checked_at) : "—"}</dd>
                </div>
              </dl>

              <button type="button" className="button v-with-icon v-test" onClick={() => void test()} disabled={testing}>
                {testing ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <RefreshCw size={16} aria-hidden="true" />}
                Test Connection
              </button>
            </section>

            <section className="v-card v-tips" aria-labelledby="tips-title">
              <h2 id="tips-title"><Info size={16} aria-hidden="true" />Tips</h2>
              <p>You can switch providers anytime. Make sure the API key has access to the selected model.</p>
            </section>
          </aside>
        </div>

        <div className="v-action-bar">
          <button type="submit" className="button primary v-with-icon v-save" disabled={saving}>
            {saving ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <Save size={16} aria-hidden="true" />}
            {saving ? "Saving..." : "Save Changes"}
          </button>
          <button type="button" className="button secondary" onClick={cancel}>
            Cancel
          </button>
        </div>
      </form>

      <div className="v-note v-note-block">
        <Info size={20} aria-hidden="true" />
        <div>
          <strong>About AI Provider Settings</strong>
          <p>Your API key is stored securely and only used to authenticate requests to your chosen provider. The backend never returns your raw key.</p>
        </div>
      </div>
    </section>
  );
}
