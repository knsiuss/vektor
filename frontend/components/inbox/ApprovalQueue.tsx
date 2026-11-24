"use client";

import { useCallback, useEffect, useState } from "react";

interface ApprovalItem {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  created_at: string;
}

export function ApprovalQueue() {
  const [items, setItems] = useState<ApprovalItem[]>([]);

  const load = useCallback(async () => {
    const res = await fetch("/api/v1/approvals");
    if (res.ok) {
      const all = (await res.json()) as ApprovalItem[];
      setItems(all.filter((i) => i.status === "pending" || i.status === "approved"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(id: string, decision: "approved" | "rejected") {
    const res = await fetch(`/api/v1/approvals/${encodeURIComponent(id)}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    if (res.ok) await load();
  }

  async function execute(id: string) {
    const res = await fetch(`/api/v1/approvals/${encodeURIComponent(id)}/execute`, {
      method: "POST",
    });
    if (res.ok) await load();
  }

  if (items.length === 0) return null;

  return (
    <section className="ops-card ops-stack">
      <strong style={{ fontSize: 14 }}>Action Approvals ({items.length})</strong>
      {items.map((item) => (
        <div
          key={item.id}
          className="ops-row"
          style={{ borderTop: "1px solid var(--color-border)", paddingTop: 10 }}
        >
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {item.tool_name}{" "}
              <span className="ops-metric-label">({item.status})</span>
            </div>
            <pre className="ops-code" style={{ marginTop: 4 }}>
              {JSON.stringify(item.arguments)}
            </pre>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {item.status === "pending" ? (
              <>
                <button type="button" onClick={() => void decide(item.id, "approved")} className="ops-btn">
                  Approve
                </button>
                <button
                  type="button"
                  onClick={() => void decide(item.id, "rejected")}
                  className="ops-btn ops-btn-ghost"
                >
                  Reject
                </button>
              </>
            ) : (
              <button type="button" onClick={() => void execute(item.id)} className="ops-btn">
                Execute
              </button>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
