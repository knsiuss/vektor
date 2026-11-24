"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { formatCompact, percentChange } from "@/lib/format";
import type {
  BudgetStatus,
  Connection,
  FeedbackItem,
  Timeseries,
  ToolUsageReport,
  Usage,
} from "@/lib/types";

import { BudgetMeter } from "./budget-meter";
import { DONUT_COLORS, Donut, Sparkline, UsageChart } from "./charts";
import { ReplyQualityCard } from "./reply-quality-card";
import { FeedbackPanel } from "./feedback-panel";
import { Calendar, Info, Layers, LoaderCircle, MessageSquare, Wrench, Zap } from "./icons";

const RANGES = [7, 30, 90] as const;

function Delta({ current, previous }: { current: number; previous: number }) {
  const change = percentChange(current, previous);
  if (change === null) return current > 0 ? <span className="v-delta up">New</span> : null;
  const up = change >= 0;
  return (
    <span className={`v-delta ${up ? "up" : "down"}`} title="Compared with the previous period of the same length">
      {up ? "\u2191" : "\u2193"} {Math.abs(change).toFixed(1)}%
    </span>
  );
}

function Kpi({ icon, label, value, previous, values }: {
  icon: ReactNode;
  label: string;
  value: number;
  previous: number;
  values: number[];
}) {
  return (
    <article className="v-kpi">
      <span className="v-kpi-icon" aria-hidden="true">{icon}</span>
      <div className="v-kpi-body">
        <p>{label}</p>
        <div className="v-kpi-value"><strong>{formatCompact(value)}</strong><Delta current={value} previous={previous} /></div>
      </div>
      <Sparkline values={values} />
    </article>
  );
}

export function TelemetryView({ connection }: { connection: Connection }) {
  const [days, setDays] = useState<number>(30);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [series, setSeries] = useState<Timeseries | null>(null);
  const [toolReport, setToolReport] = useState<ToolUsageReport | null>(null);
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
  const [budget, setBudget] = useState<BudgetStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(async (quiet: boolean) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const [usageData, seriesData, toolsData, feedbackData, budgetData] = await Promise.all([
        api<Usage>("usage", connection),
        api<Timeseries>(`usage/timeseries?days=${days}`, connection),
        api<ToolUsageReport>(`usage/tools?days=${days}&limit=6`, connection).catch(() => null),
        api<FeedbackItem[]>("usage/feedback?limit=8", connection).catch(() => []),
        api<BudgetStatus>("usage/budget", connection).catch(() => null),
      ]);
      setUsage(usageData);
      setSeries(seriesData);
      setToolReport(toolsData);
      setFeedback(feedbackData);
      setBudget(budgetData);
      setUpdatedAt(new Date());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load usage data.");
    } finally {
      setLoading(false);
    }
  }, [connection, days]);

  useEffect(() => {
    void load(false);
    const timer = window.setInterval(() => void load(true), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const points = series?.points ?? [];
  const hasActivity = points.some((point) => point.messages > 0 || point.tokens > 0);

  const models = usage?.by_model ?? [];
  const byStatus = usage?.by_status ?? {};
  const totalTokens = models.reduce((sum, item) => sum + item.total_tokens, 0);
  const segments = [
    ...models.slice(0, 3).map((item) => ({ label: item.model, value: item.total_tokens })),
    ...(models.length > 3
      ? [{ label: "Others", value: models.slice(3).reduce((sum, item) => sum + item.total_tokens, 0) }]
      : []),
  ];
  const percent = (value: number) => (totalTokens ? `${((value / totalTokens) * 100).toFixed(1)}%` : "0%");

  return (
    <section className="view v-telemetry" aria-labelledby="telemetry-title">
      <header className="view-header">
        <div>
          <h1 id="telemetry-title">Telemetry &amp; Analytics</h1>
          <p>Monitor usage, performance, and system activity.</p>
        </div>
        <label className="v-select">
          <Calendar size={17} aria-hidden="true" />
          <span className="sr-only">Time range</span>
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            {RANGES.map((range) => <option key={range} value={range}>Last {range} Days</option>)}
          </select>
        </label>
      </header>

      {error && (
        <div className="form-message error" role="alert">
          <div><strong>Could not load telemetry</strong><p>{error}</p></div>
          <button className="button secondary" onClick={() => void load(false)}>Retry</button>
        </div>
      )}

      {loading && !series ? (
        <div className="drawer-state large" role="status"><LoaderCircle className="spin" aria-hidden="true" /><p>Loading usage data</p></div>
      ) : (
        <>
          <div className="v-kpi-grid">
            <Kpi icon={<MessageSquare size={22} />} label="Total Conversations" value={series?.current.conversations ?? 0} previous={series?.previous.conversations ?? 0} values={points.map((p) => p.conversations)} />
            <Kpi icon={<Layers size={22} />} label="Total Messages" value={series?.current.messages ?? 0} previous={series?.previous.messages ?? 0} values={points.map((p) => p.messages)} />
            <Kpi icon={<Zap size={22} />} label="Total Tokens" value={series?.current.tokens ?? 0} previous={series?.previous.tokens ?? 0} values={points.map((p) => p.tokens)} />
          </div>

          <ReplyQualityCard byStatus={byStatus} />

          <section className="v-card" aria-labelledby="overview-title">
            <div className="v-card-head">
              <h2 id="overview-title">Usage Overview</h2>
              <div className="v-segmented" role="group" aria-label="Time range">
                {RANGES.map((range) => (
                  <button key={range} className={days === range ? "is-active" : ""} aria-pressed={days === range} onClick={() => setDays(range)}>{range}D</button>
                ))}
              </div>
            </div>
            <div className="v-legend">
              <span title="Plotted against left axis"><i className="dot primary" />Messages</span>
              <span title="Plotted against right axis"><i className="dot secondary" />Tokens</span>
            </div>
            {hasActivity ? <UsageChart points={points} /> : (
              <div className="v-chart-empty"><p>No activity in the last {days} days.</p><span>Start a session and your usage will appear here.</span></div>
            )}
          </section>

          <div className="v-two">
            <section className="v-card" aria-labelledby="models-title">
              <div className="v-card-head"><h2 id="models-title">Model Usage</h2><span className="v-muted">All time, by tokens</span></div>
              {segments.length === 0 ? (
                <div className="v-empty"><p>No model usage recorded yet.</p></div>
              ) : (
                <div className="v-model-body">
                  <Donut segments={segments} centerValue={percent(segments[0].value)} centerLabel={segments[0].label} />
                  <ul className="v-model-list">
                    {segments.map((segment, index) => (
                      <li key={segment.label}>
                        <i className="dot" style={{ background: DONUT_COLORS[index % DONUT_COLORS.length] }} />
                        <span>{segment.label}</span>
                        <b>{percent(segment.value)}</b>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            <section className="v-card" aria-labelledby="tools-title">
              <div className="v-card-head">
                <h2 id="tools-title">Top Tools</h2>
                {toolReport && toolReport.total_calls > 0 && (
                  <span className="v-muted">{toolReport.total_calls.toLocaleString()} calls</span>
                )}
              </div>
              {toolReport && toolReport.tools.length > 0 ? (
                <ul className="v-tools-list">
                  {toolReport.tools.map((tool) => {
                    const pct = (tool.share * 100).toFixed(1);
                    return (
                      <li className="v-tool-row" key={tool.tool_name}>
                        <span className="v-tool-label">
                          <Wrench size={14} aria-hidden="true" />
                          <span>{tool.tool_name}</span>
                        </span>
                        <span className="v-tool-track" aria-hidden="true">
                          <span className="v-tool-fill" style={{ width: `${Math.max(4, Math.round(tool.share * 100))}%` }} />
                        </span>
                        <b className="v-tool-pct" title={`${tool.calls} calls · ${Math.round(tool.success_rate * 100)}% success · ${tool.avg_duration_ms}ms avg`}>{pct}%</b>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="v-empty">
                  <Wrench size={26} aria-hidden="true" />
                  <p>No tool calls recorded yet.</p>
                  <span>Tool invocation telemetry will appear here once the assistant runs diagnostic or search tools.</span>
                </div>
              )}
            </section>
          </div>

          <BudgetMeter budget={budget} />

          <FeedbackPanel items={feedback} />

          <div className="v-note" role="status">
            <Info size={18} aria-hidden="true" />
            <span className="dot live" />
            <span>
              {updatedAt ? `Updated ${updatedAt.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : "Loading"}
              {" \u00b7 refreshes every 30 seconds \u00b7 totals are for your own sessions"}
            </span>
          </div>
        </>
      )}
    </section>
  );
}
