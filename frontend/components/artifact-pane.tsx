"use client";

import { useState } from "react";
import { Copy, Download, Maximize2, Minimize2, X } from "lucide-react";
import { EvidencePanel } from "@/components/artifacts/EvidencePanel";
import { HtmlAppViewer } from "@/components/artifacts/HtmlAppViewer";

export interface ArtifactItem {
  id: string;
  type: "document" | "table" | "chart" | string;
  title: string;
  status: string;
  version: number;
  source: Record<string, unknown>;
}

interface Block {
  id?: string;
  type: string;
  level?: number;
  text?: string;
  ordered?: boolean;
  items?: string[];
  spans?: Array<{ text: string; evidence?: string }>;
}

export function ArtifactPane({
  artifact,
  versions,
  onSelectVersion,
  onClose,
}: {
  artifact: ArtifactItem;
  versions: number[];
  onSelectVersion?: (version: number) => void;
  onClose: () => void;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [tablePage, setTablePage] = useState(0);
  const pageSize = 50;

  function handleCopy() {
    void navigator.clipboard.writeText(JSON.stringify(artifact.source, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  function handleDownload() {
    const blob = new Blob([JSON.stringify(artifact.source, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${artifact.title.replace(/[^a-z0-9-_]+/gi, "_")}_v${artifact.version}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const blocks = Array.isArray(artifact.source.blocks)
    ? (artifact.source.blocks as Block[])
    : [];
  const columns = Array.isArray(artifact.source.columns)
    ? (artifact.source.columns as string[])
    : [];
  const rows = Array.isArray(artifact.source.rows)
    ? (artifact.source.rows as Array<Array<string | number>>)
    : [];

  return (
    <aside
      aria-label={`Artifact preview: ${artifact.title}`}
      style={{
        position: fullscreen ? "fixed" : "relative",
        inset: fullscreen ? 0 : undefined,
        zIndex: fullscreen ? 60 : 20,
        width: fullscreen ? "100vw" : "440px",
        maxWidth: fullscreen ? "100vw" : "46vw",
        height: fullscreen ? "100vh" : "100%",
        display: "flex",
        flexDirection: "column",
        borderLeft: "1px solid rgba(255,255,255,0.08)",
        background: "#111113",
        color: "#f4f4f5",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
          padding: "12px 14px",
          borderBottom: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: "13px", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {artifact.title}
          </div>
          <div style={{ fontSize: "11px", color: "#a1a1aa" }}>
            {artifact.type} · v{artifact.version} · {artifact.status}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          {versions.length > 1 && onSelectVersion && (
            <select
              aria-label="Select version"
              value={artifact.version}
              onChange={(e) => onSelectVersion(Number(e.target.value))}
              style={{
                background: "#18181b",
                color: "#f4f4f5",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: "6px",
                fontSize: "11px",
                padding: "3px 6px",
              }}
            >
              {versions.map((v) => (
                <option key={v} value={v}>
                  v{v}
                </option>
              ))}
            </select>
          )}
          <button type="button" onClick={handleCopy} title={copied ? "Copied" : "Copy JSON"} className="p-1.5 rounded hover:bg-zinc-800">
            <Copy size={14} />
          </button>
          <button type="button" onClick={handleDownload} title="Download" className="p-1.5 rounded hover:bg-zinc-800">
            <Download size={14} />
          </button>
          <button type="button" onClick={() => setFullscreen((f) => !f)} title="Toggle fullscreen" className="p-1.5 rounded hover:bg-zinc-800">
            {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button type="button" onClick={onClose} title="Close preview" className="p-1.5 rounded hover:bg-zinc-800">
            <X size={14} />
          </button>
        </div>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: "16px", fontSize: "13px", lineHeight: 1.6 }}>
        {artifact.type === "document" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {blocks.map((block, idx) => {
              if (block.type === "heading") {
                return (
                  <h3 key={block.id ?? idx} style={{ fontSize: "16px", fontWeight: 600, margin: "4px 0" }}>
                    {block.text}
                  </h3>
                );
              }
              if (block.type === "list") {
                return (
                  <ul key={block.id ?? idx} style={{ paddingLeft: "18px", margin: 0 }}>
                    {(block.items ?? []).map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                );
              }
              if (block.type === "divider") {
                return <hr key={block.id ?? idx} style={{ borderColor: "rgba(255,255,255,0.08)" }} />;
              }
              return (
                <p key={block.id ?? idx} style={{ margin: 0, color: "#d4d4d8" }}>
                  {block.spans
                    ? block.spans.map((s, sIdx) => (
                        <span key={sIdx}>
                          {s.text}
                          {s.evidence && (
                            <button
                              type="button"
                              onClick={() => setSelectedEvidence(s.evidence ?? null)}
                              title={`Lihat sumber: ${s.evidence}`}
                              style={{
                                marginLeft: "3px",
                                padding: "1px 4px",
                                borderRadius: "4px",
                                border: "none",
                                cursor: "pointer",
                                background: "rgba(59,130,246,0.18)",
                                color: "#93c5fd",
                                fontSize: "10px",
                              }}
                            >
                              {s.evidence}
                            </button>
                          )}
                        </span>
                      ))
                    : block.text}
                </p>
              );
            })}
          </div>
        )}

        {artifact.type === "table" && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
              <thead>
                <tr>
                  {columns.map((col, i) => (
                    <th key={i} style={{ textAlign: "left", padding: "6px 8px", borderBottom: "1px solid rgba(255,255,255,0.12)", color: "#a1a1aa" }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(tablePage * pageSize, (tablePage + 1) * pageSize).map((row, r) => (
                  <tr key={tablePage * pageSize + r}>
                    {row.map((cell, c) => (
                      <td key={c} style={{ padding: "6px 8px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                        {String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > pageSize && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: "8px", fontSize: "11px", color: "#a1a1aa" }}>
                <span>
                  Baris {tablePage * pageSize + 1}–{Math.min((tablePage + 1) * pageSize, rows.length)} dari {rows.length}
                </span>
                <div style={{ display: "flex", gap: "6px" }}>
                  <button type="button" disabled={tablePage === 0} onClick={() => setTablePage((p) => p - 1)}>Prev</button>
                  <button type="button" disabled={(tablePage + 1) * pageSize >= rows.length} onClick={() => setTablePage((p) => p + 1)}>Next</button>
                </div>
              </div>
            )}
          </div>
        )}

        {artifact.type === "html_app" && typeof artifact.source.html === "string" && (
          <div style={{ height: "100%", minHeight: "420px", borderRadius: "10px", overflow: "hidden" }}>
            <HtmlAppViewer html={artifact.source.html} title={artifact.title} />
          </div>
        )}

        {artifact.type !== "document" && artifact.type !== "table" && artifact.type !== "html_app" && (
          <pre style={{ margin: 0, fontSize: "12px", color: "#d4d4d8", whiteSpace: "pre-wrap" }}>
            {JSON.stringify(artifact.source, null, 2)}
          </pre>
        )}
      </div>
      {selectedEvidence && (
        <EvidencePanel
          artifactId={artifact.id}
          evidenceId={selectedEvidence}
          onClose={() => setSelectedEvidence(null)}
        />
      )}
    </aside>
  );
}
