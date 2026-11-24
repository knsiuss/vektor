import math
import re
from collections.abc import Awaitable, Callable, Sequence

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")


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


async def semantic_chunk_text(
    text: str,
    *,
    embed_fn: Callable[[list[str]], Awaitable[Sequence[Sequence[float]]]],
    document_title: str = "",
    min_chunk_chars: int = 180,
    max_chunk_chars: int = 900,
    breakpoint_percentile: float = 0.20,
) -> list[str]:
    """Split text at semantic topic boundaries detected via adjacent sentence cosine drops."""
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

        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(body) if s.strip()]
        if len(sentences) <= 2 or len(body) <= min_chunk_chars:
            for seg in _sliding_window(body, chunk_size=max_chunk_chars, overlap=120):
                chunks.append(f"{prefix}{seg}")
            continue

        vectors = await embed_fn(sentences)
        sims = [
            _cosine(vectors[i], vectors[i + 1])
            for i in range(len(sentences) - 1)
        ]
        sorted_sims = sorted(sims)
        raw_idx = int(len(sorted_sims) * breakpoint_percentile)
        cutoff_idx = max(0, min(len(sorted_sims) - 1, raw_idx))
        threshold = sorted_sims[cutoff_idx]

        current: list[str] = [sentences[0]]
        current_len = len(sentences[0])
        for idx, sim in enumerate(sims):
            nxt = sentences[idx + 1]
            should_split = (
                (sim <= threshold and current_len >= min_chunk_chars)
                or (current_len + 1 + len(nxt) > max_chunk_chars and current_len >= min_chunk_chars)
            )
            if should_split:
                joined = " ".join(current).strip()
                for seg in _sliding_window(joined, chunk_size=max_chunk_chars, overlap=120):
                    chunks.append(f"{prefix}{seg}")
                current = [nxt]
                current_len = len(nxt)
            else:
                current.append(nxt)
                current_len += 1 + len(nxt)

        if current:
            joined = " ".join(current).strip()
            for seg in _sliding_window(joined, chunk_size=max_chunk_chars, overlap=120):
                chunks.append(f"{prefix}{seg}")

    return chunks


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
