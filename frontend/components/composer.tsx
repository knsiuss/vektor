"use client";

import { useEffect, useRef, useState } from "react";

import { shortModelName } from "@/lib/models";
import type {
  Connection,
  ConversationContext,
  KnowledgeDocument,
  ReasoningEffort,
  RetrievalMode,
} from "@/lib/types";

import { ChatModelPopover } from "./chat-model-popover";
import { ContextMeter } from "./context-meter";

import {
  ArrowUp,
  Brain,
  ChevronDown,
  ChevronRight,
  FileText,
  Image,
  Layers,
  Plus,
  Settings2,
  ShieldAlert,
  Square,
} from "./icons";

export const ACCEPTED_FILE_TYPES = ".pdf,.docx,.md,.txt,.csv,.json,.png,.jpg,.jpeg";
export const MAX_FILE_SIZE = 15 * 1024 * 1024;
const RETRIEVAL_LABELS: Record<RetrievalMode, string> = {
  auto: "Auto (Agentic)",
  always: "Always On",
  explicit: "Explicit",
  off: "Off",
};
const REASONING_LABELS: Record<string, string> = {
  "": "Off",
  low: "Low",
  medium: "Medium",
  high: "High",
};

export function validateDocument(file: File) {
  if (!/\.(pdf|docx|md|txt|csv|json|png|jpe?g)$/i.test(file.name)) return "Choose a PDF, DOCX, Markdown, text, CSV, JSON, PNG, or JPG file.";
  if (file.size > MAX_FILE_SIZE) return "File size must be 15 MB or less.";
  return null;
}

export function Composer({
  value,
  onValueChange,
  onSend,
  onUpload,
  disabled,
  documents,
  mode,
  onModeChange,
  scope,
  onScopeChange,
  allowMutating,
  onAllowMutatingChange,
  reasoningEffort,
  onReasoningEffortChange,
  onStop,
  model,
  modelContextLength,
  context,
  compacting,
  onCompact,
  connection,
  activeProfileId,
  onSelectModel,
  onOpenSettings,
}: {
  value: string;
  onValueChange: (value: string) => void;
  onSend: (value: string) => void;
  onUpload: (file: File) => Promise<void>;
  disabled: boolean;
  documents: KnowledgeDocument[];
  mode: RetrievalMode;
  onModeChange: (mode: RetrievalMode) => void;
  scope: string;
  onScopeChange: (id: string) => void;
  allowMutating: boolean;
  onAllowMutatingChange: (value: boolean) => void;
  reasoningEffort: ReasoningEffort | null;
  onReasoningEffortChange: (value: ReasoningEffort | null) => void;
  /** When set, the send button turns into a Stop button while an answer is being written. */
  onStop?: () => void;
  /** Active model id, shown next to the reasoning effort in the footer. */
  model?: string | null;
  modelContextLength?: number | null;
  context?: ConversationContext | null;
  compacting?: boolean;
  onCompact?: () => void;
  connection?: Connection;
  activeProfileId?: string | null;
  onSelectModel?: (model: string, profileId: string | null, contextLength?: number | null) => void;
  /** Jump to provider settings from the model menu. */
  onOpenSettings?: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLInputElement>(null);
  const plusRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [uploading, setUploading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [panel, setPanel] = useState<"rag" | "reasoning" | "options" | null>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`;
  }, [value]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !menuRef.current?.contains(target) && !plusRef.current?.contains(target)) {
        setMenuOpen(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        setPanel(null);
        plusRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!modelMenuOpen && !pickerOpen) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !modelMenuRef.current?.contains(target)) {
        setModelMenuOpen(false);
        setPickerOpen(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setModelMenuOpen(false);
        setPickerOpen(false);
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [modelMenuOpen, pickerOpen]);

  function submit() {
    if (!value.trim() || disabled || uploading) return;
    onSend(value.trim());
    setMenuOpen(false);
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setMenuOpen(false);
    try { await onUpload(file); } finally { setUploading(false); }
  }

  return (
    <div className="composer-area">
      <div className="composer-menu-anchor">
        {menuOpen && (
          <div className="composer-plus-menu" ref={menuRef} role="menu" aria-label="Message options">
            {panel !== "rag" && panel !== "reasoning" ? (
              <>
                <button role="menuitem" onClick={() => imageRef.current?.click()}>
                  <Image size={19} aria-hidden="true" />
                  <span><strong>Upload Image</strong><small>PNG, JPG, WEBP</small></span>
                </button>
                <button role="menuitem" onClick={() => fileRef.current?.click()}>
                  <FileText size={19} aria-hidden="true" />
                  <span><strong>Upload File</strong><small>PDF, DOCX, TXT, CSV</small></span>
                </button>
                <div className="composer-menu-divider" />
                <label className="composer-menu-switch">
                  <ShieldAlert size={18} aria-hidden="true" />
                  <span>Allow Mutating Tools</span>
                  <span className="switch-control">
                    <input type="checkbox" role="switch" aria-label="Allow mutating tools" checked={allowMutating} onChange={(event) => onAllowMutatingChange(event.target.checked)} />
                  </span>
                </label>
                <button role="menuitem" onClick={() => setPanel("rag")}>
                  <Layers size={18} aria-hidden="true" />
                  <span><strong>RAG Mode</strong><small>{RETRIEVAL_LABELS[mode]}</small></span>
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
                <button role="menuitem" onClick={() => setPanel("reasoning")}>
                  <Brain size={18} aria-hidden="true" />
                  <span><strong>Reasoning</strong><small>{reasoningEffort ? `${REASONING_LABELS[reasoningEffort]} effort` : "Off"}</small></span>
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
                <button role="menuitem" aria-expanded={panel === "options"} onClick={() => setPanel(panel === "options" ? null : "options")}>
                  <Settings2 size={18} aria-hidden="true" />
                  <span><strong>More Options</strong><small>{mode === "explicit" ? "Document scope and shortcuts" : "Composer shortcuts"}</small></span>
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
                {panel === "options" && (
                  <div className="composer-more-options">
                    {mode === "explicit" && (
                      <div className="scope-control">
                        <label htmlFor="document-scope">Document scope</label>
                        <select id="document-scope" aria-label="Document scope" value={scope} onChange={(event) => onScopeChange(event.target.value)}>
                          <option value="">All documents</option>
                          {documents.map((doc) => <option value={doc.id} key={doc.id}>{doc.title}</option>)}
                        </select>
                      </div>
                    )}
                    <p><kbd>Enter</kbd> to send<span> / </span><kbd>Shift + Enter</kbd> for a new line</p>
                  </div>
                )}
              </>
            ) : panel === "reasoning" ? (
              <>
                <button className="composer-menu-back" onClick={() => setPanel(null)}><ChevronDown size={17} aria-hidden="true" /><span>Reasoning</span></button>
                {(["", "low", "medium", "high"] as const).map((option) => {
                  const selected = (reasoningEffort ?? "") === option;
                  return (
                    <button
                      className={selected ? "is-selected" : ""}
                      role="menuitemradio"
                      aria-checked={selected}
                      key={option || "off"}
                      onClick={() => { onReasoningEffortChange(option === "" ? null : (option as ReasoningEffort)); setPanel(null); }}
                    >
                      <span>{REASONING_LABELS[option] === "Off" ? "Off" : `${REASONING_LABELS[option]} effort`}</span>
                      {selected && <span aria-hidden="true">&#10003;</span>}
                    </button>
                  );
                })}
              </>
            ) : (
              <>
                <button className="composer-menu-back" onClick={() => setPanel(null)}><ChevronDown size={17} aria-hidden="true" /><span>RAG Mode</span></button>
                {(Object.keys(RETRIEVAL_LABELS) as RetrievalMode[]).map((option) => (
                  <button className={mode === option ? "is-selected" : ""} role="menuitemradio" aria-checked={mode === option} key={option} onClick={() => { onModeChange(option); setPanel(null); }}>
                    <span>{RETRIEVAL_LABELS[option]}</span>
                    {mode === option && <span aria-hidden="true">&#10003;</span>}
                  </button>
                ))}
              </>
            )}
          </div>
        )}
      </div>
      <form className={`composer ${allowMutating ? "mutating-enabled" : ""}`} onSubmit={(event) => { event.preventDefault(); submit(); }}>
        <input ref={fileRef} id="quick-document-upload" className="sr-only" type="file" accept={ACCEPTED_FILE_TYPES} aria-label="Attach document" onChange={(event) => { void upload(event.target.files?.[0]); event.target.value = ""; }} />
        <input ref={imageRef} id="image-upload" className="sr-only" type="file" accept=".png,.jpg,.jpeg,.webp" aria-label="Attach image" onChange={(event) => { void upload(event.target.files?.[0]); event.target.value = ""; }} />
        <button ref={plusRef} type="button" className="attach-button" aria-label="Open message options" title="Upload and message options" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => { setMenuOpen(true); setPanel(null); }} disabled={uploading}>
          <Plus size={22} aria-hidden="true" />
        </button>
        <div className="composer-input-wrap">
          <label htmlFor="message-input" className="sr-only">Message Vektor</label>
          <textarea
            id="message-input"
            ref={textareaRef}
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Write a message..."
            rows={1}
            maxLength={16000}
            disabled={disabled}
          />
          {uploading && <span className="composer-hint" role="status">Indexing document...</span>}
        </div>
        <div className="composer-controls">
          {disabled && onStop ? (
            <button type="button" className="send-button is-stop" onClick={onStop} aria-label="Stop generating" title="Stop generating (Esc)"><Square size={16} fill="currentColor" aria-hidden="true" /></button>
          ) : (
            <button type="submit" className="send-button" disabled={!value.trim() || disabled || uploading} aria-label={disabled ? "Waiting for response" : "Send message"} title={disabled ? "Waiting for response" : "Send message"}><ArrowUp size={20} aria-hidden="true" /></button>
          )}
        </div>
      </form>
      <div className="composer-meta">
        <span className="composer-disclaimer">
          Vektor is AI and can make mistakes. Please double-check responses.
        </span>
        <span className="composer-meta-right" ref={modelMenuRef}>
          <button
            type="button"
            className={`composer-model-trigger ${modelMenuOpen ? "is-open" : ""}`}
            aria-haspopup="menu"
            aria-expanded={modelMenuOpen}
            onClick={() => setModelMenuOpen((current) => !current)}
            title="Model and reasoning effort"
          >
            <span className="composer-model">{model ? shortModelName(model) : "No model"}</span>
            <span className="composer-effort-label">
              {reasoningEffort ? REASONING_LABELS[reasoningEffort] : "Effort"}
            </span>
          </button>
          {modelMenuOpen && (
            <div className="composer-model-menu" role="menu" aria-label="Model and effort">
              <div className="composer-model-menu-head">
                <strong>{model ? shortModelName(model) : "No model selected"}</strong>
                <small>{model ?? "Pick one in Settings"}</small>
                <span className="composer-model-menu-check" aria-hidden="true">&#10003;</span>
              </div>
              <div className="composer-model-menu-row is-static">
                <span>Effort</span>
                <span className="composer-model-menu-value">
                  {reasoningEffort ? REASONING_LABELS[reasoningEffort] : "Off"}
                </span>
              </div>
              <div className="composer-model-menu-options" role="group" aria-label="Reasoning effort">
                {(["", "low", "medium", "high"] as const).map((option) => {
                  const selected = (reasoningEffort ?? "") === option;
                  return (
                    <button
                      type="button"
                      role="menuitemradio"
                      aria-checked={selected}
                      key={option || "off"}
                      className={selected ? "is-selected" : ""}
                      onClick={() => onReasoningEffortChange(option === "" ? null : (option as ReasoningEffort))}
                    >
                      {REASONING_LABELS[option]}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                className="composer-model-menu-row"
                role="menuitem"
                onClick={() => {
                  setModelMenuOpen(false);
                  if (connection && onSelectModel) {
                    setPickerOpen(true);
                  } else {
                    onOpenSettings?.();
                  }
                }}
              >
                <span>More models</span>
                <ChevronRight size={16} aria-hidden="true" />
              </button>
            </div>
          )}
          {pickerOpen && connection && onSelectModel && (
            <ChatModelPopover
              connection={connection}
              selectedModel={model ?? null}
              selectedProfileId={activeProfileId ?? null}
              onSelect={(nextModel, nextProfileId, ctxLen) => {
                onSelectModel(nextModel, nextProfileId, ctxLen);
                setPickerOpen(false);
              }}
              onManageApis={
                onOpenSettings
                  ? () => {
                      setPickerOpen(false);
                      onOpenSettings();
                    }
                  : undefined
              }
            />
          )}
          {context && context.total_messages > 0 && onCompact && (
            <ContextMeter
              context={context}
              compacting={Boolean(compacting)}
              onCompact={onCompact}
              model={model}
              modelContextLength={modelContextLength}
            />
          )}
        </span>
      </div>
    </div>
  );
}
