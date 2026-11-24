"use client";

import { useEffect, useState } from "react";

interface AnalyticsData {
  total_connectors: number;
  total_sessions: number;
  active_handovers: number;
  ai_deflection_rate: number;
}

export function ChannelAnalyticsCards() {
  const [data, setData] = useState<AnalyticsData | null>(null);

  useEffect(() => {
    fetch("/api/v1/channels/analytics")
      .then((res) => (res.ok ? (res.json() as Promise<AnalyticsData>) : null))
      .then((payload) => {
        if (payload) setData(payload);
      })
      .catch(() => {});
  }, []);

  if (!data) return null;

  const cards = [
    { label: "Total Connectors", value: String(data.total_connectors) },
    { label: "Total Sesi Chat", value: String(data.total_sessions) },
    { label: "Active Handovers", value: String(data.active_handovers) },
    { label: "AI Deflection Rate", value: `${Math.round(data.ai_deflection_rate * 100)}%` },
  ];

  return (
    <div className="ops-grid-4">
      {cards.map((c) => (
        <div key={c.label} className="ops-card" style={{ marginBottom: 0 }}>
          <div className="ops-metric-label">{c.label}</div>
          <div className="ops-metric-value">{c.value}</div>
        </div>
      ))}
    </div>
  );
}
