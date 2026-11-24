"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

interface EvalCaseItem {
  id: string;
  question: string;
  expected_facts: string[];
  forbidden_claims: string[];
}

interface EvalRunResult {
  total: number;
  passed: number;
  pass_rate: number;
  results: Array<{
    case_id: string;
    question: string;
    passed: boolean;
    missing_facts: string[];
    triggered_forbidden: string[];
  }>;
}

interface KnowledgeAudit {
  total_documents: number;
  stale_doc_ids: string[];
  conflicts: Array<{ doc_a_title: string; doc_b_title: string; similarity: number }>;
}

export function EvalsManager() {
  const [cases, setCases] = useState<EvalCaseItem[]>([]);
  const [audit, setAudit] = useState<KnowledgeAudit | null>(null);
  const [runResult, setRunResult] = useState<EvalRunResult | null>(null);
  const [question, setQuestion] = useState("");
  const [expected, setExpected] = useState("");
  const [forbidden, setForbidden] = useState("");
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    const [cRes, aRes] = await Promise.all([
      fetch("/api/v1/evals/cases"),
      fetch("/api/v1/knowledge/audit"),
    ]);
    if (cRes.ok) setCases((await cRes.json()) as EvalCaseItem[]);
    if (aRes.ok) setAudit((await aRes.json()) as KnowledgeAudit);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    const res = await fetch("/api/v1/evals/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question.trim(),
        expected_facts: expected.split(",").map((s) => s.trim()).filter(Boolean),
        forbidden_claims: forbidden.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    });
    if (res.ok) {
      setQuestion("");
      setExpected("");
      setForbidden("");
      await load();
    }
  }

  async function handleDelete(id: string) {
    const res = await fetch(`/api/v1/evals/cases/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (res.ok) await load();
  }

  async function handleRun() {
    setRunning(true);
    try {
      const res = await fetch("/api/v1/evals/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) setRunResult((await res.json()) as EvalRunResult);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="ops-stack">
      {audit && (
        <section className="ops-card ops-stack">
          <strong style={{ fontSize: 14 }}>Knowledge Freshness &amp; Conflict Audit</strong>
          <div className="ops-grid-4" style={{ marginBottom: 0 }}>
            <div>
              <div className="ops-metric-label">Total Dokumen</div>
              <div className="ops-metric-value">{audit.total_documents}</div>
            </div>
            <div>
              <div className="ops-metric-label">Dokumen Stale (&gt;90 hari)</div>
              <div className="ops-metric-value">{audit.stale_doc_ids.length}</div>
            </div>
            <div>
              <div className="ops-metric-label">Potensi Konflik</div>
              <div className="ops-metric-value">{audit.conflicts.length}</div>
            </div>
          </div>
          {audit.conflicts.map((c, idx) => (
            <div key={idx} className="ops-metric-label">
              Konflik ({Math.round(c.similarity * 100)}%): &ldquo;{c.doc_a_title}&rdquo; vs &ldquo;{c.doc_b_title}&rdquo;
            </div>
          ))}
        </section>
      )}

      <form onSubmit={handleCreate} className="ops-card ops-stack">
        <div className="ops-row">
          <strong style={{ fontSize: 14 }}>Golden Q&amp;A Eval Suite</strong>
          <button
            type="button"
            onClick={() => void handleRun()}
            disabled={running || cases.length === 0}
            className="ops-btn"
          >
            {running ? "Menjalankan Eval..." : `Run Eval (${cases.length})`}
          </button>
        </div>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Pertanyaan uji (mis. Berapa lama masa garansi?)"
          className="ops-input"
          required
        />
        <input
          value={expected}
          onChange={(e) => setExpected(e.target.value)}
          placeholder="Fakta wajib muncul, pisahkan koma (mis. 14 hari, struk asli)"
          className="ops-input"
        />
        <input
          value={forbidden}
          onChange={(e) => setForbidden(e.target.value)}
          placeholder="Klaim terlarang, pisahkan koma (opsional, mis. seumur hidup)"
          className="ops-input"
        />
        <div>
          <button type="submit" className="ops-btn ops-btn-ghost">
            Tambah Test Case
          </button>
        </div>
      </form>

      {runResult && (
        <section className="ops-card ops-stack">
          <strong style={{ fontSize: 14 }}>
            Hasil Eval: {runResult.passed}/{runResult.total} Lulus ({Math.round(runResult.pass_rate * 100)}%)
          </strong>
          {runResult.results.map((r) => (
            <div key={r.case_id} className="ops-metric-label">
              [{r.passed ? "PASS" : "FAIL"}] {r.question}
              {r.missing_facts.length > 0 && ` — Kurang: ${r.missing_facts.join(", ")}`}
              {r.triggered_forbidden.length > 0 && ` — Terlarang: ${r.triggered_forbidden.join(", ")}`}
            </div>
          ))}
        </section>
      )}

      {cases.map((c) => (
        <div key={c.id} className="ops-card ops-row">
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{c.question}</div>
            <div className="ops-metric-label">
              Wajib: {c.expected_facts.join(", ") || "-"} | Terlarang: {c.forbidden_claims.join(", ") || "-"}
            </div>
          </div>
          <button type="button" onClick={() => void handleDelete(c.id)} className="ops-btn ops-btn-danger">
            Hapus
          </button>
        </div>
      ))}
    </div>
  );
}
