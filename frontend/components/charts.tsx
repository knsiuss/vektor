"use client";

import { useId, useRef, useState } from "react";

import { formatCompact } from "@/lib/format";
import type { DailyPoint } from "@/lib/types";

type Point = { x: number; y: number };

/** Smooth line through the points using horizontal-tangent cubic segments. */
function smoothPath(points: Point[]): string {
  if (points.length === 0) return "";
  let d = `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1];
    const cur = points[i];
    const cx = ((prev.x + cur.x) / 2).toFixed(2);
    d += ` C${cx},${prev.y.toFixed(2)} ${cx},${cur.y.toFixed(2)} ${cur.x.toFixed(2)},${cur.y.toFixed(2)}`;
  }
  return d;
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return nice * magnitude;
}

function shortDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "2-digit", timeZone: "UTC" });
}

function longDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function Sparkline({ values }: { values: number[] }) {
  const id = useId();
  const width = 160;
  const height = 56;
  const max = Math.max(...values, 1);
  const points = values.map((value, index) => ({
    x: values.length === 1 ? width / 2 : (index / (values.length - 1)) * width,
    y: height - 4 - (value / max) * (height - 12),
  }));
  const line = smoothPath(points);
  return (
    <svg className="v-sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--chart-primary)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--chart-primary)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {points.length > 1 && <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${id}-fill)`} />}
      <path d={line} fill="none" stroke="var(--chart-primary)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const W = 900;
const H = 300;
const M = { left: 52, right: 60, top: 14, bottom: 30 };

export function UsageChart({ points }: { points: DailyPoint[] }) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const maxMessages = niceMax(Math.max(...points.map((p) => p.messages), 0));
  const maxTokens = niceMax(Math.max(...points.map((p) => p.tokens), 0));
  const xAt = (index: number) => M.left + (points.length === 1 ? plotW / 2 : (index / (points.length - 1)) * plotW);
  const yAt = (value: number, max: number) => M.top + plotH - (value / max) * plotH;

  const messagePoints = points.map((p, i) => ({ x: xAt(i), y: yAt(p.messages, maxMessages) }));
  const tokenPoints = points.map((p, i) => ({ x: xAt(i), y: yAt(p.tokens, maxTokens) }));
  const baseline = M.top + plotH;

  const labelCount = Math.min(5, points.length);
  const labelIndexes = Array.from({ length: labelCount }, (_, i) =>
    labelCount === 1 ? 0 : Math.round((i / (labelCount - 1)) * (points.length - 1)),
  );

  function onMove(event: React.MouseEvent<HTMLDivElement>) {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect || points.length === 0) return;
    const x = ((event.clientX - rect.left) / rect.width) * W;
    const ratio = (x - M.left) / plotW;
    setHover(Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1)))));
  }

  const active = hover === null ? null : points[hover];
  const activeLeft = hover === null ? 0 : (xAt(hover) / W) * 100;

  return (
    <div className="v-chart" ref={ref} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Daily messages and tokens over ${points.length} days`}>
        <defs>
          <linearGradient id={`${id}-a`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-primary)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="var(--chart-primary)" stopOpacity="0" />
          </linearGradient>
          <linearGradient id={`${id}-b`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-secondary)" stopOpacity="0.2" />
            <stop offset="100%" stopColor="var(--chart-secondary)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1 / 3, 2 / 3, 1].map((fraction) => {
          const y = M.top + plotH - fraction * plotH;
          return (
            <g key={fraction}>
              <line x1={M.left} x2={W - M.right} y1={y} y2={y} className="v-grid" />
              <text x={M.left - 10} y={y + 4} textAnchor="end" className="v-axis">{formatCompact(maxMessages * fraction)}</text>
              <text x={W - M.right + 10} y={y + 4} textAnchor="start" className="v-axis v-axis-right">{formatCompact(maxTokens * fraction)}</text>
            </g>
          );
        })}
        {labelIndexes.map((index) => (
          <g key={index}>
            <line x1={xAt(index)} x2={xAt(index)} y1={M.top} y2={baseline} className="v-grid-v" />
            <text x={xAt(index)} y={H - 8} textAnchor="middle" className="v-axis">{shortDate(points[index].date)}</text>
          </g>
        ))}
        {points.length > 1 && (
          <>
            <path d={`${smoothPath(tokenPoints)} L${xAt(points.length - 1)},${baseline} L${xAt(0)},${baseline} Z`} fill={`url(#${id}-b)`} />
            <path d={`${smoothPath(messagePoints)} L${xAt(points.length - 1)},${baseline} L${xAt(0)},${baseline} Z`} fill={`url(#${id}-a)`} />
          </>
        )}
        <path d={smoothPath(tokenPoints)} fill="none" stroke="var(--chart-secondary)" strokeWidth="1.8" />
        <path d={smoothPath(messagePoints)} fill="none" stroke="var(--chart-primary)" strokeWidth="2" />
        {hover !== null && (
          <g>
            <line x1={xAt(hover)} x2={xAt(hover)} y1={M.top} y2={baseline} className="v-cursor" />
            <circle cx={xAt(hover)} cy={messagePoints[hover].y} r="4.5" fill="var(--chart-primary)" stroke="var(--color-card)" strokeWidth="2" />
            <circle cx={xAt(hover)} cy={tokenPoints[hover].y} r="4.5" fill="var(--chart-secondary)" stroke="var(--color-card)" strokeWidth="2" />
          </g>
        )}
      </svg>
      {active && (
        <div className="v-tooltip" style={{ left: `${Math.min(Math.max(activeLeft, 14), 86)}%` }} role="status">
          <strong>{longDate(active.date)}</strong>
          <span><i className="dot primary" />Messages<b title={active.messages.toLocaleString()}>{formatCompact(active.messages)}</b></span>
          <span><i className="dot secondary" />Tokens<b title={active.tokens.toLocaleString()}>{formatCompact(active.tokens)}</b></span>
        </div>
      )}
    </div>
  );
}

export const DONUT_COLORS = ["var(--chart-primary)", "var(--chart-secondary)", "var(--chart-tertiary)", "var(--chart-quaternary)"];

export function Donut({
  segments,
  centerValue,
  centerLabel,
}: {
  segments: { label: string; value: number }[];
  centerValue: string;
  centerLabel: string;
}) {
  const radius = 72;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((sum, item) => sum + item.value, 0);
  let offset = 0;
  return (
    <div className="v-donut">
      <svg viewBox="0 0 200 200" role="img" aria-label="Share of tokens by model">
        <circle cx="100" cy="100" r={radius} fill="none" stroke="var(--color-surface)" strokeWidth="26" />
        <g transform="rotate(-90 100 100)">
          {total > 0 && segments.map((segment, index) => {
            const length = (segment.value / total) * circumference;
            const circle = (
              <circle
                key={segment.label}
                cx="100"
                cy="100"
                r={radius}
                fill="none"
                stroke={DONUT_COLORS[index % DONUT_COLORS.length]}
                strokeWidth="26"
                strokeDasharray={`${Math.max(length - 1.5, 0)} ${circumference}`}
                strokeDashoffset={-offset}
              />
            );
            offset += length;
            return circle;
          })}
        </g>
      </svg>
      <div className="v-donut-center"><strong>{centerValue}</strong><span>{centerLabel}</span></div>
    </div>
  );
}
