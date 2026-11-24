import re
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("CARD", re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b")),
    ("NIK", re.compile(r"\b\d{16}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+62|62|08)\d{8,12}\b")),
)


@dataclass(frozen=True)
class RedactionResult:
    sanitized: str
    mapping: dict[str, str]


class PIIScrubber:
    """Deterministic PII masker applied before sending user text to external LLMs."""

    def redact(self, text: str) -> RedactionResult:
        mapping: dict[str, str] = {}
        counters: dict[str, int] = {}
        sanitized = text

        for label, pattern in _PATTERNS:
            def _replace(match: re.Match[str], lbl: str = label) -> str:
                raw = match.group(0)
                idx = counters.get(lbl, 0) + 1
                counters[lbl] = idx
                token = f"[REDACTED_{lbl}_{idx}]"
                mapping[token] = raw
                return token

            sanitized = pattern.sub(_replace, sanitized)

        return RedactionResult(sanitized=sanitized, mapping=mapping)

    def restore(self, text: str, mapping: dict[str, str]) -> str:
        restored = text
        for token, raw in mapping.items():
            restored = restored.replace(token, raw)
        return restored
