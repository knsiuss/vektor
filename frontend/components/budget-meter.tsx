import type { BudgetStatus } from "@/lib/types";

import { formatCompact } from "@/lib/format";
import { Gauge } from "./icons";

const STATE_COPY: Record<BudgetStatus["state"], { label: string; tone: string }> = {
  unlimited: { label: "No limit", tone: "muted" },
  ok: { label: "Within budget", tone: "ok" },
  warning: { label: "Approaching limit", tone: "warning" },
  exhausted: { label: "Budget used up", tone: "danger" },
};

export function BudgetMeter({ budget }: { budget: BudgetStatus | null }) {
  if (!budget) return null;

  const copy = STATE_COPY[budget.state];
  const percent = budget.limit_tokens
    ? Math.min(100, Math.round((budget.used_tokens / budget.limit_tokens) * 100))
    : 0;

  return (
    <section className="v-card" aria-labelledby="budget-title">
      <div className="v-card-head">
        <h2 id="budget-title">Monthly Token Budget</h2>
        <span className={`v-budget-state ${copy.tone}`}>{copy.label}</span>
      </div>
      {budget.limit_tokens === null ? (
        <div className="v-empty">
          <Gauge size={26} aria-hidden="true" />
          <p>No ceiling configured for this tenant.</p>
          <span>
            An administrator can set one with <code>PUT /api/v1/admin/budget</code>. Requests
            are rejected once the ceiling is reached.
          </span>
        </div>
      ) : (
        <div className="v-budget-body">
          <p className="v-budget-numbers">
            <strong>{formatCompact(budget.used_tokens)}</strong>
            <span> of {formatCompact(budget.limit_tokens)} tokens used in {budget.month}</span>
          </p>
          <div className="v-budget-track" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Monthly token budget used">
            <span className={`v-budget-fill ${copy.tone}`} style={{ width: `${percent}%` }} />
          </div>
          <p className="v-budget-left">
            {budget.state === "exhausted"
              ? "New requests are rejected until the ceiling is raised or the month resets."
              : `${formatCompact(budget.limit_tokens - budget.used_tokens)} tokens left this month.`}
          </p>
        </div>
      )}
    </section>
  );
}
