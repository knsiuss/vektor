"use client";

import { contextLevel, contextPercent, formatTokens } from "@/lib/context";
import type { ConversationContext } from "@/lib/types";

type ContextMeterProps = {
  context: ConversationContext;
  compacting: boolean;
  onCompact: () => void;
};

/**
 * Prompt-window indicator for the active conversation, plus the compact action.
 * Mirrors the Claude Desktop pattern: how full the context is, and one click to shrink it.
 */
export function ContextMeter({ context, compacting, onCompact }: ContextMeterProps) {
  const percent = contextPercent(context);
  const level = contextLevel(percent);
  const canCompact = context.total_messages > 2 && !compacting;

  return (
    <div className={`context-meter is-${level}`} role="group" aria-label="Conversation context usage">
      <div className="context-meter-copy">
        <span className="context-meter-label">Context</span>
        <span className="context-meter-value">
          {formatTokens(context.used_tokens)} / {formatTokens(context.limit_tokens)} tokens
        </span>
      </div>
      <div
        className="context-meter-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label="Context window used"
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <span className="context-meter-percent">{percent}%</span>
      <button
        type="button"
        className="context-meter-compact"
        onClick={onCompact}
        disabled={!canCompact}
        title="Summarize older turns into one message to free up context"
      >
        {compacting ? "Compacting…" : "Compact"}
      </button>
    </div>
  );
}
