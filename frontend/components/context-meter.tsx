"use client";

import { useEffect, useRef, useState } from "react";

import { contextLevel, contextPercent, formatTokens } from "@/lib/context";
import type { ConversationContext } from "@/lib/types";

type ContextMeterProps = {
  context: ConversationContext;
  compacting: boolean;
  onCompact: () => void;
  model?: string | null;
  modelContextLength?: number | null;
};

function inferModelLimit(model?: string | null): number | null {
  if (!model) return null;
  const lower = model.toLowerCase();
  if (lower.includes("gemini")) return 1_000_000;
  if (lower.includes("claude")) return 200_000;
  if (lower.includes("gpt-4") || lower.includes("deepseek") || lower.includes("qwen")) return 128_000;
  return null;
}

export function ContextMeter({
  context,
  compacting,
  onCompact,
  model,
  modelContextLength,
}: ContextMeterProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const effectiveLimit = modelContextLength || inferModelLimit(model) || context.limit_tokens;
  const effectiveContext = { ...context, limit_tokens: effectiveLimit };
  const percent = contextPercent(effectiveContext);
  const level = contextLevel(percent);
  const canCompact = context.total_messages > 2 && !compacting;
  const remaining = Math.max(0, effectiveLimit - context.used_tokens);

  const radius = 9;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.min(100, Math.max(0, percent)) / 100) * circumference;

  return (
    <span className={`context-ring-wrap is-${level}`} ref={wrapRef}>
      <button
        type="button"
        className="context-ring-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Context window ${percent}% used`}
        title={`Context: ${formatTokens(context.used_tokens)} / ${formatTokens(effectiveLimit)} (${percent}%)`}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
          <circle
            cx="12"
            cy="12"
            r={radius}
            fill="none"
            stroke="var(--color-border)"
            strokeWidth="2.5"
          />
          <circle
            cx="12"
            cy="12"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            transform="rotate(-90 12 12)"
          />
        </svg>
      </button>

      {open && (
        <div className="context-popover" role="dialog" aria-label="Context window">
          <div className="context-popover-head">
            <span>Context window</span>
            <strong>
              {formatTokens(context.used_tokens)} / {formatTokens(effectiveLimit)} ({percent}%)
            </strong>
          </div>
          <div
            className="context-meter-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <span style={{ width: `${percent}%` }} />
          </div>
          <div className="context-popover-foot">
            <span>{formatTokens(remaining)} remaining</span>
            <button
              type="button"
              className="context-meter-compact"
              onClick={() => {
                onCompact();
                setOpen(false);
              }}
              disabled={!canCompact}
            >
              {compacting ? "Compacting…" : "Compact session"}
            </button>
          </div>
        </div>
      )}
    </span>
  );
}
