"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { documentType, formatDateTime } from "@/lib/format";
import type { Citation, Connection, KnowledgeDocument } from "@/lib/types";

import { ACCEPTED_FILE_TYPES, validateDocument } from "./composer";
import { ConfirmDialog } from "./drawer";
import {
  BookOpen,
  Check,
  CircleAlert,
  FileText,
  LoaderCircle,
  MoreVertical,
  Moon,
  RefreshCw,
  Search,
  Sun,
  Trash2,
  UploadCloud,
} from "./icons";

type Tab = "documents" | "search" | "upload";
type UploadState = { id: string; name: string; state: "uploading" | "done" | "error"; message?: string };

export function KnowledgeView({
  connection,
  documents,
  loading,
  error,
  onRefresh,
  onEvent,
  theme,
  onToggleTheme,
}: {
  connection: Connection;
  documents: KnowledgeDocument[];
  loading: boolean;
  error: string | null;
  onRefresh: () => Promise<void>;
  onEvent: (label: string) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}) {
  const [tab, setTab] = useState<Tab>("documents");
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [filter, setFilter] = useState("");
  const [menuId, setMenuId] = useState<string | null>(null);
  const [target, setTarget] = useState<KnowledgeDocument | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Citation[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!menuId) return;
    const close = () => setMenuId(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menuId]);

  const patchUpload = (id: string, patch: Partial<UploadState>) =>
    setUploads((list) => list.map((item) => (item.id === id ? { ...item, ...patch } : item)));

  const uploadFiles = useCallback(async (files: File[]) => {
    setNotice("");
    for (const file of files) {
      const id = `${file.name}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const invalid = validateDocument(file);
      if (invalid) {
        setUploads((list) => [{ id, name: file.name, state: "error", message: invalid }, ...list]);
        continue;
      }
      setUploads((list) => [{ id, name: file.name, state: "uploading" }, ...list]);
      const body = new FormData();
      body.append("file", file);
      try {
        await api("knowledge/documents/upload", connection, {
          method: "POST",
          body,
          timeoutMs: Math.max(connection.timeoutSeconds ?? 30, 120) * 1000,
        });
        patchUpload(id, { state: "done" });
        onEvent(`Uploaded ${file.name}`);
      } catch (cause) {
        patchUpload(id, { state: "error", message: cause instanceof Error ? cause.message : "Upload failed. Try again." });
      }
    }
    await onRefresh();
  }, [connection, onEvent, onRefresh]);

  async function remove() {
    if (!target) return;
    setDeleting(true);
    try {
      await api(`knowledge/documents/${target.id}`, connection, { method: "DELETE" });
      setNotice(`${target.title} and its indexed chunks were deleted.`);
      onEvent(`Deleted ${target.title}`);
      setTarget(null);
      await onRefresh();
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : "Document deletion failed.");
      setTarget(null);
    } finally {
      setDeleting(false);
    }
  }

  async function reindex(doc: KnowledgeDocument) {
    setMenuId(null);
    setNotice("");
    try {
      await api(`knowledge/documents/${doc.id}/reindex`, connection, { method: "POST" });
      setNotice(`${doc.title} was re-indexed with the current embedding model.`);
      onEvent(`Re-indexed ${doc.title}`);
      await onRefresh();
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : "Re-indexing failed.");
    }
  }

  async function runSearch(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearchError("");
    try {
      setResults(await api<Citation[]>("knowledge/search", connection, {
        method: "POST",
        body: { query: query.trim(), top_k: 5, min_score: 0.2 },
      }));
    } catch (cause) {
      setResults(null);
      setSearchError(cause instanceof Error ? cause.message : "Search failed. Try again.");
    } finally {
      setSearching(false);
    }
  }

  const totalChunks = documents.reduce((sum, doc) => sum + doc.chunk_count, 0);
  const visible = documents.filter((doc) => doc.title.toLowerCase().includes(filter.trim().toLowerCase()));

  const dropzone = (
    <div
      className={`v-dropzone ${dragging ? "is-dragging" : ""}`}
      role="button"
      tabIndex={0}
      aria-label="Upload documents. Drag and drop files here, or press Enter to browse."
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inputRef.current?.click(); } }}
      onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); void uploadFiles(Array.from(event.dataTransfer.files)); }}
    >
      <span className="v-dropzone-icon" aria-hidden="true"><UploadCloud size={26} strokeWidth={1.75} /></span>
      <h3>Upload Documents</h3>
      <p>Drag &amp; drop files here, or click to browse</p>
      <div className="v-format-list" aria-label="Supported file types">
        {["PDF", "DOCX", "MD", "TXT", "CSV", "JSON", "PNG", "JPG"].map((ext) => (
          <span className="v-format-chip" key={ext}>{ext}</span>
        ))}
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        accept={ACCEPTED_FILE_TYPES}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          if (files.length > 0) void uploadFiles(files);
        }}
      />
    </div>
  );

  const uploadList = uploads.length > 0 && (
    <ul className="v-uploads" aria-label="Upload progress">
      {uploads.slice(0, 6).map((item) => (
        <li key={item.id} className={item.state}>
          {item.state === "uploading" && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
          {item.state === "done" && <Check size={16} aria-hidden="true" />}
          {item.state === "error" && <CircleAlert size={16} aria-hidden="true" />}
          <span>{item.name}</span>
          <em>{item.state === "uploading" ? "Indexing\u2026" : item.state === "done" ? "Indexed" : item.message}</em>
        </li>
      ))}
    </ul>
  );

  const sandbox = (
    <section className="v-card v-sandbox" aria-labelledby="sandbox-title">
      <h2 id="sandbox-title"><Search size={19} aria-hidden="true" /> Search Sandbox</h2>
      <p>Try searching your knowledge base</p>
      <form onSubmit={(event) => void runSearch(event)} role="search">
        <div className="v-input-wrap">
          <Search size={17} aria-hidden="true" />
          <input type="search" aria-label="Search query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. database failover procedure..." />
        </div>
        <button type="submit" className="button primary" disabled={searching || !query.trim()}>{searching ? "Searching..." : "Search"}</button>
      </form>
      {searchError && <div className="form-message error" role="alert"><div><strong>Search failed</strong><p>{searchError}</p></div></div>}
      {results && results.length === 0 && <p className="v-hint" role="status">No matches above the relevance threshold.</p>}
      {results && results.length > 0 && (
        <ul className="v-results">
          {results.map((hit) => (
            <li key={`${hit.document_id}-${hit.chunk_index}`}>
              <div><FileText size={15} aria-hidden="true" /><strong>{hit.document_title}</strong><span>{Math.round(hit.score * 100)}% match</span></div>
              <p>{hit.content}</p>
              <small>Chunk {hit.chunk_index + 1}</small>
            </li>
          ))}
        </ul>
      )}
    </section>
  );

  return (
    <section className="view v-knowledge" aria-labelledby="knowledge-title">
      <header className="view-header">
        <div className="v-title-row">
          <span className="v-title-icon" aria-hidden="true"><BookOpen size={24} /></span>
          <div>
            <h1 id="knowledge-title">Knowledge Base</h1>
            <p>Manage your documents and search through your knowledge base.</p>
          </div>
        </div>
        <button type="button" className="v-theme" onClick={onToggleTheme} aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
          {theme === "dark" ? <Sun size={19} aria-hidden="true" /> : <Moon size={19} aria-hidden="true" />}
        </button>
      </header>

      <div className="v-tabs" role="tablist" aria-label="Knowledge base sections">
        {([
          ["documents", "Documents", <FileText key="d" size={17} aria-hidden="true" />],
          ["search", "Search", <Search key="s" size={17} aria-hidden="true" />],
          ["upload", "Upload", <UploadCloud key="u" size={17} aria-hidden="true" />],
        ] as const).map(([id, label, icon]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "is-active" : ""} onClick={() => setTab(id)}>{icon}{label}</button>
        ))}
      </div>

      {notice && <div className="form-message success" role="status"><Check size={18} aria-hidden="true" /><div><p>{notice}</p></div></div>}
      {error && <div className="form-message error" role="alert"><div><strong>Could not load documents</strong><p>{error}</p></div><button className="button secondary" onClick={() => void onRefresh()}>Retry</button></div>}

      {(tab === "documents" || tab === "upload") && <>{dropzone}{uploadList}</>}

      {tab === "documents" && (
        <section className="v-docs" aria-labelledby="docs-title">
          <div className="v-docs-head">
            <h2 id="docs-title">
              Your Documents
              <span className="v-count">{documents.length} {documents.length === 1 ? "file" : "files"}</span>
              {documents.length > 0 && (
                <span className="v-count v-count-muted">{totalChunks.toLocaleString()} {totalChunks === 1 ? "chunk" : "chunks"}</span>
              )}
            </h2>
            <div className="v-input-wrap v-filter">
              <Search size={16} aria-hidden="true" />
              <input type="search" aria-label="Search documents" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search documents..." />
            </div>
          </div>
          {loading && documents.length === 0 ? (
            <div className="drawer-state" role="status"><LoaderCircle className="spin" aria-hidden="true" /><p>Loading documents</p></div>
          ) : visible.length === 0 ? (
            <div className="v-empty">
              <FileText size={28} aria-hidden="true" />
              <p>{documents.length === 0 ? "No documents indexed yet." : "No documents match your search."}</p>
              {documents.length === 0 && <span>Upload a PDF, DOCX, Markdown or text file to make it searchable in chat.</span>}
            </div>
          ) : (
            <div className="v-table-wrap">
              <table className="v-table">
                <caption className="sr-only">Indexed documents</caption>
                <thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Chunks</th><th scope="col">Status</th><th scope="col">Updated</th><th scope="col" className="v-right">Actions</th></tr></thead>
                <tbody>
                  {visible.map((doc) => {
                    const type = documentType(doc.source, doc.title);
                    return (
                      <tr key={doc.id}>
                        <td><span className="v-doc-cell"><span className={`v-file-badge ${type.tone}`} aria-hidden="true">{type.badge}</span><span className="v-doc-name">{doc.title}</span></span></td>
                        <td>{type.label}</td>
                        <td>{doc.chunk_count.toLocaleString()}</td>
                        <td><span className="v-status-ok"><i className="dot live" />Indexed</span></td>
                        <td>
                          <span className="v-doc-updated">
                            {formatDateTime(doc.last_synced_at ?? doc.created_at)}
                            {doc.is_stale && <span className="v-stale-pill">Stale</span>}
                          </span>
                        </td>
                        <td className="v-right">
                          <div className="v-menu-wrap">
                            <button className="icon-button" aria-label={`Actions for ${doc.title}`} aria-haspopup="menu" aria-expanded={menuId === doc.id} onClick={(event) => { event.stopPropagation(); setMenuId(menuId === doc.id ? null : doc.id); }}><MoreVertical size={18} aria-hidden="true" /></button>
                            {menuId === doc.id && (
                              <div className="v-menu" role="menu">
                                <button role="menuitem" onClick={() => void reindex(doc)}><RefreshCw size={15} aria-hidden="true" /> Re-index document</button>
                                <button role="menuitem" className="danger" onClick={() => setTarget(doc)}><Trash2 size={15} aria-hidden="true" /> Delete document</button>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {(tab === "documents" || tab === "search") && sandbox}

      {target && (
        <ConfirmDialog
          title="Delete this document?"
          description={`${target.title} and all of its indexed chunks will be permanently removed from the knowledge base.`}
          confirmLabel="Delete document"
          busy={deleting}
          onConfirm={() => void remove()}
          onClose={() => setTarget(null)}
        />
      )}
    </section>
  );
}
