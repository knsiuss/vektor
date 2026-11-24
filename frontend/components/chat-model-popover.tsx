"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { api, listProviderModels } from "@/lib/api";
import { cleanModelName, fallbackModels, formatPrice } from "@/lib/models";
import type { Connection, ProviderModel, ProviderName, ProviderProfile } from "@/lib/types";

import { Check, LoaderCircle, Search, Settings } from "./icons";

export function ChatModelPopover({
  connection,
  selectedModel,
  selectedProfileId,
  onSelect,
  onManageApis,
}: {
  connection: Connection;
  selectedModel: string | null;
  selectedProfileId: string | null;
  onSelect: (model: string, profileId: string | null, contextLength?: number | null) => void;
  onManageApis?: () => void;
}) {
  const [profiles, setProfiles] = useState<ProviderProfile[]>([]);
  const [activeTab, setActiveTab] = useState<string>(selectedProfileId ?? "default");
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api<ProviderProfile[]>("providers/profiles", connection)
      .then(setProfiles)
      .catch(() => setProfiles([]));
  }, [connection]);

  const loadModels = useCallback(
    async (tabId: string) => {
      setLoading(true);
      setError(null);
      try {
        if (tabId === "default") {
          const catalog = await listProviderModels(connection, {
            provider: "openrouter",
            base_url: null,
            api_key: null,
          });
          setModels(
            catalog.models.length > 0 ? catalog.models : fallbackModels("openrouter"),
          );
          if (catalog.error) setError(catalog.error);
        } else {
          const profile = profiles.find((p) => p.id === tabId);
          const catalog = await api<{ models: ProviderModel[]; error: string | null }>(
            `providers/profiles/${tabId}/models`,
            connection,
            { method: "POST" },
          );
          const prov = (profile?.provider as ProviderName) || "custom";
          setModels(catalog.models.length > 0 ? catalog.models : fallbackModels(prov));
          if (catalog.error) setError(catalog.error);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not load models.");
        setModels(fallbackModels("openrouter"));
      } finally {
        setLoading(false);
      }
    },
    [connection, profiles],
  );

  useEffect(() => {
    void loadModels(activeTab);
  }, [activeTab, loadModels]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return models.slice(0, 40);
    return models
      .filter((m) => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
      .slice(0, 40);
  }, [models, query]);

  return (
    <div className="chat-model-popover" role="dialog" aria-label="Choose chat model">
      <div className="cmp-profiles" role="tablist" aria-label="Configured APIs">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "default"}
          className={`cmp-tab ${activeTab === "default" ? "is-active" : ""}`}
          onClick={() => setActiveTab("default")}
        >
          Default API
        </button>
        {profiles.map((p) => (
          <button
            type="button"
            role="tab"
            key={p.id}
            aria-selected={activeTab === p.id}
            className={`cmp-tab ${activeTab === p.id ? "is-active" : ""}`}
            onClick={() => setActiveTab(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="cmp-search">
        <Search size={14} aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search model..."
          autoFocus
        />
      </div>

      {error && <p className="cmp-err">{error}</p>}

      <div className="cmp-list" role="listbox">
        {loading ? (
          <div className="cmp-loading">
            <LoaderCircle size={15} className="spin" aria-hidden="true" />
            <span>Loading models...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="cmp-loading">No matching models.</div>
        ) : (
          filtered.map((item) => {
            const profileId = activeTab === "default" ? null : activeTab;
            const isSelected =
              selectedModel === item.id && (selectedProfileId ?? null) === profileId;
            return (
              <button
                type="button"
                role="option"
                aria-selected={isSelected}
                key={item.id}
                className={`cmp-row ${isSelected ? "is-selected" : ""}`}
                onClick={() => onSelect(item.id, profileId, item.context_length ?? null)}
              >
                <span className="cmp-row-name">
                  <strong>{cleanModelName(item)}</strong>
                  <small>{item.id}</small>
                </span>
                <span className="cmp-row-right">
                  {item.is_free === true && <span className="cmp-badge">Free</span>}
                  {item.is_free === false && (
                    <span className="cmp-price">{formatPrice(item.prompt_price_per_million)}</span>
                  )}
                  {isSelected && <Check size={14} aria-hidden="true" />}
                </span>
              </button>
            );
          })
        )}
      </div>

      {onManageApis && (
        <button type="button" className="cmp-footer" onClick={onManageApis}>
          <Settings size={14} aria-hidden="true" />
          <span>Manage APIs in Settings</span>
        </button>
      )}
    </div>
  );
}
