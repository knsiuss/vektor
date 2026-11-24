"""Multi-format exporter (Markdown, CSV, JSON, HTML) from a single Artifact IR."""

from __future__ import annotations

import csv
import html
import io
import json
import re
from typing import Any


def sanitize_filename(title: str, version: int, ext: str) -> str:
    """Return a safe download filename with no path traversal or special chars."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", title).strip("_") or "artifact"
    return f"{slug[:64]}_v{version}.{ext}"


def export_artifact_ir(
    *,
    artifact_type: str,
    title: str,
    source: dict[str, Any],
    fmt: str,
) -> tuple[bytes, str, str]:
    """Convert an Artifact IR into (bytes, media_type, extension)."""
    normalized = fmt.lower().strip()
    if normalized == "json":
        return (
            json.dumps(source, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
            "json",
        )

    if normalized == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        columns = source.get("columns") or []
        rows = source.get("rows") or []
        if isinstance(columns, list) and columns:
            writer.writerow([str(c) for c in columns])
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, list):
                    writer.writerow([str(cell) for cell in row])
        return buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8", "csv"

    if normalized in ("md", "markdown"):
        lines: list[str] = [f"# {title}", ""]
        for block in source.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "heading":
                level = max(1, min(6, int(block.get("level") or 2)))
                lines.append(f"{'#' * level} {block.get('text', '')}")
            elif btype == "list":
                for idx, item in enumerate(block.get("items") or [], start=1):
                    prefix = f"{idx}." if block.get("ordered") else "-"
                    lines.append(f"{prefix} {item}")
            elif btype == "quote":
                lines.append(f"> {block.get('text', '')}")
            elif btype == "divider":
                lines.append("---")
            else:
                spans = block.get("spans")
                text = (
                    "".join(str(s.get("text", "")) for s in spans)
                    if isinstance(spans, list)
                    else str(block.get("text", ""))
                )
                lines.append(text)
            lines.append("")
        return "\n".join(lines).encode("utf-8"), "text/markdown; charset=utf-8", "md"

    if normalized == "html":
        if artifact_type == "html_app" and isinstance(source.get("html"), str):
            return source["html"].encode("utf-8"), "text/html; charset=utf-8", "html"
        escaped_title = html.escape(title)
        body_parts = [f"<h1>{escaped_title}</h1>"]
        for block in source.get("blocks") or []:
            if isinstance(block, dict):
                spans = block.get("spans")
                text = (
                    "".join(str(s.get("text", "")) for s in spans)
                    if isinstance(spans, list)
                    else str(block.get("text", ""))
                )
                body_parts.append(f"<p>{html.escape(text)}</p>")
        doc = (
            f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{escaped_title}</title></head>"
            f"<body>{''.join(body_parts)}</body></html>"
        )
        return doc.encode("utf-8"), "text/html; charset=utf-8", "html"

    raise ValueError(f"Unsupported export format: {fmt}")
