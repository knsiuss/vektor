import re
from dataclasses import dataclass
from typing import Any

_NUMERIC_CLAIM_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    tool_name: str
    parameters: dict[str, Any]
    source_snippet: str


class UnverifiedNumericClaimError(Exception):
    """Raised when a business/numeric claim lacks an evidence_ref."""


def validate_ir_evidence(source: dict[str, Any]) -> list[str]:
    """Validate that numeric spans in document blocks carry an evidence_ref.

    Returns a list of block IDs that contain unverified numeric claims.
    """
    unverified_blocks: list[str] = []
    blocks = source.get("blocks", [])
    if not isinstance(blocks, list):
        return unverified_blocks

    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("id", "unknown"))
        if block.get("type") != "paragraph":
            continue
        spans = block.get("spans", [])
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict):
                continue
            text = str(span.get("text", ""))
            if _NUMERIC_CLAIM_RE.search(text) and not span.get("evidence"):
                unverified_blocks.append(block_id)
                break
    return unverified_blocks


def truncate_source_snippet(raw: str, max_chars: int = 2000) -> str:
    """Truncate raw evidence data for safe display in the UI."""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + "\n... [truncated]"
