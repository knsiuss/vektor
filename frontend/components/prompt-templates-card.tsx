"use client";

import { useCallback, useEffect, useState } from "react";

import { getPrompts, resetPrompt, savePrompt } from "@/lib/api";
import type { Connection, PromptTemplate } from "@/lib/types";

import { LoaderCircle } from "./icons";

type PromptTemplatesCardProps = {
  connection: Connection;
};

/** Markdown persona (and future agent prompts) the user can edit without touching the repo. */
export function PromptTemplatesCard({ connection }: PromptTemplatesCardProps) {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "saving">("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = templates.find((template) => template.key === activeKey) ?? templates[0];

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const loaded = await getPrompts(connection);
      setTemplates(loaded);
      setActiveKey((current) => current ?? loaded[0]?.key ?? null);
      setDraft(loaded[0]?.content ?? "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load prompt templates.");
    } finally {
      setState("idle");
    }
  }, [connection]);

  useEffect(() => {
    void load();
  }, [load]);

  const select = (key: string) => {
    const template = templates.find((item) => item.key === key);
    setActiveKey(key);
    setDraft(template?.content ?? "");
    setMessage(null);
    setError(null);
  };

  const save = async () => {
    if (!active || !draft.trim()) return;
    setState("saving");
    setError(null);
    try {
      const updated = await savePrompt(connection, active.key, draft.trim());
      setTemplates((list) => list.map((item) => (item.key === updated.key ? updated : item)));
      setDraft(updated.content);
      setMessage("Template saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the template.");
    } finally {
      setState("idle");
    }
  };

  const reset = async () => {
    if (!active) return;
    setState("saving");
    setError(null);
    try {
      await resetPrompt(connection, active.key);
      await load();
      setMessage("Reverted to the shipped default.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reset the template.");
    } finally {
      setState("idle");
    }
  };

  return (
    <section className="v-card" aria-labelledby="prompts-title">
      <div className="v-card-head">
        <h2 id="prompts-title">Prompt Templates</h2>
        <span className="v-muted">Markdown, per user</span>
      </div>
      <p className="v-card-sub">
        Edit how Vektor behaves. Changes apply to your next turn and never touch the repo.
      </p>

      {templates.length > 1 && (
        <label className="v-field">
          <span>Template</span>
          <select value={active?.key ?? ""} onChange={(event) => select(event.target.value)}>
            {templates.map((template) => (
              <option key={template.key} value={template.key}>{template.label}</option>
            ))}
          </select>
        </label>
      )}

      {active && (
        <>
          <label className="v-field">
            <span>
              {active.label}
              {active.is_custom ? " · customised" : " · default"}
            </span>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={14}
              spellCheck={false}
              className="prompt-editor"
              aria-label={`${active.label} markdown`}
            />
          </label>
          <div className="prompt-editor-actions">
            <button type="button" className="button primary" onClick={() => void save()} disabled={state !== "idle" || !draft.trim()}>
              {state === "saving" ? <LoaderCircle className="is-spinning" size={15} aria-hidden="true" /> : null}
              Save template
            </button>
            <button type="button" className="button secondary" onClick={() => void reset()} disabled={state !== "idle" || !active.is_custom}>
              Reset to default
            </button>
            <span className="v-muted">{draft.length} chars</span>
          </div>
        </>
      )}

      {message && <div className="form-message success" role="status"><div><strong>{message}</strong></div></div>}
      {error && <div className="form-message error" role="alert"><div><strong>Prompt error</strong><p>{error}</p></div></div>}
    </section>
  );
}
