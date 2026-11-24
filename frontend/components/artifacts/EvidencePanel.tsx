"use client";

import { useEffect, useState } from "react";

interface EvidenceDetail {
  evidence_id: string;
  tool_name: string;
  parameters: Record<string, unknown>;
  source_snippet: string;
}

interface EvidencePanelProps {
  artifactId: string;
  evidenceId: string | null;
  onClose: () => void;
}

export function EvidencePanel({ artifactId, evidenceId, onClose }: EvidencePanelProps) {
  const [data, setData] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!evidenceId) return;
    setError(null);
    fetch(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/evidence/${encodeURIComponent(evidenceId)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error("Evidence not found");
        return (await res.json()) as EvidenceDetail;
      })
      .then(setData)
      .catch(() => setError("Sumber evidence tidak ditemukan."));
  }, [artifactId, evidenceId]);

  if (!evidenceId) return null;

  return (
    <aside className="border-l border-slate-200 bg-slate-50 p-4 text-xs w-80 overflow-y-auto">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm">Sumber Evidence ({evidenceId})</h3>
        <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-800">
          Tutup
        </button>
      </div>
      {error && <p className="text-red-600">{error}</p>}
      {data && (
        <div className="space-y-3">
          <div>
            <div className="font-medium text-slate-600">Tool / Kode</div>
            <pre className="mt-1 rounded bg-white p-2 border border-slate-200 overflow-x-auto">
              {data.tool_name}
            </pre>
          </div>
          <div>
            <div className="font-medium text-slate-600">Parameter</div>
            <pre className="mt-1 rounded bg-white p-2 border border-slate-200 overflow-x-auto">
              {JSON.stringify(data.parameters, null, 2)}
            </pre>
          </div>
          <div>
            <div className="font-medium text-slate-600">Data Sumber</div>
            <pre className="mt-1 rounded bg-white p-2 border border-slate-200 overflow-x-auto whitespace-pre-wrap">
              {data.source_snippet}
            </pre>
          </div>
        </div>
      )}
    </aside>
  );
}
