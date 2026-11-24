import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from modules.knowledge.schemas import RetrievedChunk

_FENCE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`([^`\n]{2,120})`")
_CITATION_RE = re.compile(r"\[(\d+)\](?!\()")
_HOSTNAME_RE = re.compile(
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\b|\b(?:\d{1,3}\.){3}\d{1,3}\b",
    re.IGNORECASE,
)
_ERROR_CODE_RE = re.compile(
    r"\b(?:ERR_[A-Z0-9_]+|ORA-\d{4,5}|INC-\d{4,}|SQLSTATE\s+[A-Z0-9]{5})\b"
)
_DOC_FILE_EXTS = (
    ".md", ".pdf", ".docx", ".txt", ".csv", ".json", ".yaml", ".yml", ".log", ".png", ".jpg", ".jpeg", ".webp"
)


class GroundingReport(BaseModel):
    """Zero-LLM verification report checking citation accuracy and ops token grounding."""

    model_config = ConfigDict(frozen=True)

    cited_indices: list[int] = Field(default_factory=list)
    invalid_citations: list[int] = Field(default_factory=list)
    has_context_without_citations: bool = False
    ungrounded_tokens: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def verify_grounding(
    reply: str,
    citations: Sequence[RetrievedChunk],
    tool_outputs: Sequence[str] = (),
) -> GroundingReport:
    """Verify bracketed [n] citations and check ops commands, hosts, and error codes against context."""
    prose_only = _FENCE_RE.sub(" ", reply)
    max_index = len(citations)

    cited_indices: list[int] = []
    invalid_citations: list[int] = []
    for match in _CITATION_RE.finditer(prose_only):
        idx = int(match.group(1))
        if 1 <= idx <= max_index:
            if idx not in cited_indices:
                cited_indices.append(idx)
        elif idx not in invalid_citations:
            invalid_citations.append(idx)

    has_context_without_citations = bool(citations) and not cited_indices

    haystack = "\n".join(
        [*(chunk.content for chunk in citations), *(chunk.document_title for chunk in citations), *tool_outputs]
    ).lower()

    candidates: list[str] = []
    for match in _INLINE_CODE_RE.finditer(reply):
        token = match.group(1).strip()
        if _looks_like_command_or_identifier(token):
            candidates.append(token)

    for block in _FENCE_RE.findall(reply):
        inner_lines = block.splitlines()[1:-1]
        for raw_line in inner_lines:
            line = raw_line.strip()
            if line and not line.startswith("#") and _looks_like_command_or_identifier(line):
                candidates.append(line)

    for match in _HOSTNAME_RE.finditer(reply):
        host = match.group(0).strip()
        if not host.lower().endswith(_DOC_FILE_EXTS):
            candidates.append(host)

    for match in _ERROR_CODE_RE.finditer(reply):
        candidates.append(match.group(0).strip())

    ungrounded_tokens: list[str] = []
    for token in candidates:
        lowered = token.lower()
        if lowered not in haystack and token not in ungrounded_tokens:
            ungrounded_tokens.append(token)

    warnings: list[str] = []
    if has_context_without_citations:
        warnings.append("Response had retrieved context but included no inline [n] citations.")
    if invalid_citations:
        bad = ", ".join(f"[{idx}]" for idx in invalid_citations)
        warnings.append(f"Response referenced non-existent citation index(es): {bad}.")
    if ungrounded_tokens:
        listed = ", ".join(ungrounded_tokens[:6])
        warnings.append(f"Potentially ungrounded tokens not found in documents or tool outputs: {listed}.")

    return GroundingReport(
        cited_indices=cited_indices,
        invalid_citations=invalid_citations,
        has_context_without_citations=has_context_without_citations,
        ungrounded_tokens=ungrounded_tokens,
        warnings=warnings,
    )


def _looks_like_command_or_identifier(token: str) -> bool:
    if len(token) < 3:
        return False
    return any(ch in token for ch in (" ", "/", "-", "_", "."))
