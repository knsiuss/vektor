"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listProviderModels } from "@/lib/api";
import {
  cleanModelName,
  fallbackModels,
  filterModels,
  formatContextLength,
  formatPrice,
  groupModels,
} from "@/lib/models";
import type { Connection, ProviderModel, ProviderName } from "@/lib/types";

import { Check, ChevronDown, LoaderCircle, RefreshCw, Search } from "./icons";

type ModelPickerProps = {
  connection: Connection;
  provider: ProviderName;
  baseUrl: string;
  apiKey: string;
  value: string;
  onChange: (model: string) => void;
};

type LoadState = "idle" | "loading" | "ready" | "failed";

/**
 * Model chooser backed by the provider's own catalogue.
 * Results are grouped by price band so the cheapest usable option is always at the top.
 */
export function ModelPicker({ connection, provider, baseUrl, apiKey, value, onChange }: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<LoadState>("idle");
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [manualOpen, setManualOpen] = useState(false);
  const [manual, setManual] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [source, setSource] = useState<"provider" | "directory">("provider");
  const [usedFallback, setUsedFallback] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const catalog = await listProviderModels(connection, {
        provider,
        base_url: baseUrl || null,
        api_key: apiKey || null,
      });
      const listed = catalog.models.length > 0 ? catalog.models : fallbackModels(provider);
      setModels(listed);
      setEndpoint(catalog.endpoint ?? "");
      setSource(catalog.source);
      setError(catalog.error);
      setUsedFallback(catalog.models.length === 0);
      setState(catalog.error ? "failed" : "ready");
    } catch (cause) {
      setModels(fallbackModels(provider));
      setError(cause instanceof Error ? cause.message : "Could not load models.");
      setUsedFallback(true);
      setState("failed");
    }
  }, [apiKey, baseUrl, connection, provider]);

  // A different provider or endpoint means a different catalogue: drop the old one.
  useEffect(() => {
    setState("idle");
    setModels([]);
    setError(null);
    setEndpoint("");
    setUsedFallback(false);
    setSource("provider");
    setQuery("");
    setActiveIndex(0);
  }, [provider, baseUrl]);

  useEffect(() => {
    if (open && state === "idle") void load();
  }, [open, state, load]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const visible = useMemo(() => filterModels(models, { query, freeOnly }), [models, query, freeOnly]);
  const groups = useMemo(() => groupModels(visible), [visible]);
  const flat = useMemo(() => groups.flatMap((group) => group.models), [groups]);
  const freeCount = models.filter((model) => model.is_free === true).length;
  const selectedModel = models.find((model) => model.id === value);

  const choose = (modelId: string) => {
    const trimmed = modelId.trim();
    if (!trimmed) return;
    onChange(trimmed);
    setOpen(false);
    setManualOpen(false);
    setManual("");
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, flat.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
      return;
    }
    if (event.key === "Enter" && flat[activeIndex]) {
      event.preventDefault();
      choose(flat[activeIndex].id);
    }
  };

  // Keep the keyboard cursor inside the scroll area.
  useEffect(() => {
    if (!open) return;
    const active = listRef.current?.querySelector<HTMLElement>(".model-picker-row.is-active");
    active?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, freeOnly]);

  return (
    <div className="model-picker" ref={panelRef}>
      <button
        type="button"
        className={`model-picker-trigger ${open ? "is-open" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={value ? "model-picker-value" : "model-picker-placeholder"}>
          {value || "Select a model"}
        </span>
        {selectedModel?.is_free === true && <span className="model-picker-trigger-hint">Free</span>}
        {selectedModel?.is_free === false && (
          <span className="model-picker-trigger-price">
            {formatPrice(selectedModel.prompt_price_per_million)}
          </span>
        )}
        <ChevronDown size={16} aria-hidden="true" />
      </button>

      {open && (
        <div className="model-picker-panel" role="dialog" aria-label="Choose a model" onKeyDown={onKeyDown}>
          <div className="model-picker-search-row">
            <Search size={15} aria-hidden="true" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search models…"
              aria-label="Search models"
            />
            <button
              type="button"
              className={`model-picker-chip ${freeOnly ? "is-on" : ""}`}
              aria-pressed={freeOnly}
              onClick={() => setFreeOnly((current) => !current)}
              title={freeCount > 0 ? `${freeCount} free models available` : "No free models listed"}
            >
              Free only
            </button>
            <button
              type="button"
              className="model-picker-icon"
              onClick={() => void load()}
              disabled={state === "loading"}
              aria-label="Refresh model list"
              title="Refresh model list"
            >
              <RefreshCw size={14} className={state === "loading" ? "is-spinning" : ""} aria-hidden="true" />
            </button>
          </div>

          <div className="model-picker-list" role="listbox" aria-label="Available models" ref={listRef}>
            {state === "loading" && (
              <p className="model-picker-note">
                <LoaderCircle size={14} className="is-spinning" aria-hidden="true" /> Loading models…
              </p>
            )}
            {state !== "loading" && flat.length === 0 && (
              <p className="model-picker-note">
                {error ?? "No model matches this search."}
              </p>
            )}

            {groups.map((group) => (
              <div className="model-picker-group" key={group.key}>
                <p className="model-picker-group-label">
                  {group.label}
                  <span>{group.models.length}</span>
                </p>
                {group.models.map((model) => {
                  const index = flat.indexOf(model);
                  const selected = model.id === value;
                  return (
                    <button
                      type="button"
                      key={model.id}
                      role="option"
                      aria-selected={selected}
                      className={`model-picker-row ${selected ? "is-selected" : ""} ${index === activeIndex ? "is-active" : ""}`}
                      onMouseMove={() => setActiveIndex(index)}
                      onClick={() => choose(model.id)}
                    >
                      <span className="model-picker-row-copy">
                        <span className="model-picker-row-title">{cleanModelName(model)}</span>
                        <span className="model-picker-row-id">{model.id}</span>
                      </span>
                      <span className="model-picker-row-meta">
                        {model.context_length ? (
                          <span className="model-picker-ctx">{formatContextLength(model.context_length)}</span>
                        ) : null}
                        {model.is_free === true ? (
                          <span className="model-tag is-free">Free</span>
                        ) : model.is_free === false ? (
                          <span className="model-picker-price">
                            {formatPrice(model.prompt_price_per_million)}
                          </span>
                        ) : null}
                        {selected && <Check size={15} aria-hidden="true" />}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>

          <div className="model-picker-footer">
            <span className="model-picker-source">
              {usedFallback
                ? "Built-in list"
                : source === "directory"
                  ? `Newest from ${hostOf(endpoint) || "the public directory"}`
                  : `Live from ${hostOf(endpoint) || provider}`}
              {flat.length > 0 ? ` · ${flat.length} models` : ""}
            </span>
            <button
              type="button"
              className="model-picker-link"
              onClick={() => setManualOpen((current) => !current)}
            >
              {manualOpen ? "Cancel" : "Use a custom id"}
            </button>
          </div>

          {manualOpen && (
            <div className="model-picker-manual">
              <input
                autoFocus
                value={manual}
                onChange={(event) => setManual(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") choose(manual);
                }}
                placeholder="provider/model-id"
                aria-label="Custom model id"
              />
              <button type="button" onClick={() => choose(manual)} disabled={!manual.trim()}>
                Use
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
