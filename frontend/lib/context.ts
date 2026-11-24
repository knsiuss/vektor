import type { ConversationContext } from "./types";

/** Percentage of the prompt window in use, clamped to 0-100 for the meter. */
export function contextPercent(context: ConversationContext): number {
  if (context.limit_tokens <= 0) return 0;
  const percent = (context.used_tokens / context.limit_tokens) * 100;
  return Math.min(100, Math.max(0, Math.round(percent)));
}

export type ContextLevel = "low" | "medium" | "high";

/** Drives the meter colour: green below half, amber past 50%, red past 80%. */
export function contextLevel(percent: number): ContextLevel {
  if (percent >= 80) return "high";
  if (percent >= 50) return "medium";
  return "low";
}

/** Compact token label: 850 -> "850", 3500 -> "3.5k". */
export function formatTokens(value: number): string {
  if (value < 1000) return String(value);
  const thousands = value / 1000;
  return `${thousands >= 10 ? Math.round(thousands) : thousands.toFixed(1)}k`;
}
