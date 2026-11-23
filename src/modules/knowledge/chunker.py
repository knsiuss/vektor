import re

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


def chunk_text(
    text: str,
    *,
    document_title: str = "",
    chunk_size: int = 700,
    overlap: int = 120,
) -> list[str]:
    """Split text into Markdown-aware overlapping chunks enriched with section headers."""
    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        return []

    sections = _split_by_headings(normalized)
    chunks: list[str] = []

    for section_title, body in sections:
        prefix_parts = [f"Doc: {document_title}"] if document_title else []
        if section_title:
            prefix_parts.append(f"Section: {section_title}")
        prefix = f"[{' | '.join(prefix_parts)}]\n" if prefix_parts else ""

        for raw_segment in _sliding_window(body, chunk_size=chunk_size, overlap=overlap):
            chunks.append(f"{prefix}{raw_segment}")

    return chunks


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = ""
    buffer: list[str] = []

    for line in text.split("\n"):
        match = _HEADING_RE.match(line.strip())
        if match:
            body = "\n".join(buffer).strip()
            if body:
                sections.append((current_heading, body))
            current_heading = match.group(2).strip()
            buffer = []
        else:
            buffer.append(line)

    trailing = "\n".join(buffer).strip()
    if trailing:
        sections.append((current_heading, trailing))

    return sections or [("", text)]


def _sliding_window(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    segments: list[str] = []
    step = max(1, chunk_size - overlap)
    start = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            newline_break = text.rfind("\n", start + step // 2, end)
            space_break = text.rfind(" ", start + step // 2, end)
            best_break = max(newline_break, space_break)
            if best_break > start:
                end = best_break

        piece = text[start:end].strip()
        if piece:
            segments.append(piece)

        if end >= length:
            break
        start = max(start + 1, end - overlap)

    return segments
