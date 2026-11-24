"""Parse the assistant's structured reply envelope: answer, clarify, or unknown.

The model is asked to lead with a ``<<status=...>>`` marker. Everything after the marker is
either plain answer text or a small JSON object for clarify/unknown. Parsing is deliberately
forgiving: a malformed envelope must never cost the user their answer.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["answer", "clarify", "unknown"]

STATUS_MARKER = re.compile(r"^\s*<<\s*status\s*=\s*([a-zA-Z]+)\s*>>\s*", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$", re.IGNORECASE)
MAX_OPTIONS = 4


class EvidenceRef(BaseModel):
    """Pointer to something the answer relied on, never free-text evidence."""

    kind: Literal["citation", "tool", "db"] = "citation"
    index: int | None = None
    label: str | None = None


class AssistantEnvelope(BaseModel):
    """Normalized assistant turn returned by the runtime and persisted with the message."""

    status: Status = "answer"
    answer: str = ""
    clarifying_question: str | None = None
    options: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @property
    def display_text(self) -> str:
        """Text a client should show when it does not understand `status`."""
        if self.status == "clarify":
            return self.clarifying_question or self.answer
        return self.answer


def parse_assistant_output(raw: str) -> AssistantEnvelope:
    """Turn model output into a normalized envelope, tolerating broken formatting."""
    text = (raw or "").strip()
    if not text:
        return AssistantEnvelope(status="answer", answer="")

    marker = STATUS_MARKER.match(text)
    status: str = marker.group(1).lower() if marker else "answer"
    body = text[marker.end() :].strip() if marker else text

    payload = _as_object(body)
    if payload is not None:
        return _normalize(status, payload)

    return _normalize(status, {"answer": body})


def _as_object(body: str) -> dict | None:
    """Accept a bare JSON object or one wrapped in a markdown fence."""
    candidate = body
    fence = _FENCE.match(body)
    if fence:
        candidate = fence.group(1).strip()
    if not candidate.startswith("{"):
        return None
    try:
        parsed = json.loads(candidate)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize(marker_status: str, payload: dict) -> AssistantEnvelope:
    status = marker_status if marker_status in ("answer", "clarify", "unknown") else "answer"
    answer = _text(payload.get("answer"))
    question = _text(payload.get("clarifying_question")) or _text(payload.get("question"))
    options = _options(payload.get("options"))
    evidence = _evidence(payload.get("evidence"))

    if status == "clarify":
        # A clarification without a question is not usable; fall back to whatever text came.
        if not question:
            question = answer
        if not question:
            return AssistantEnvelope(status="unknown", answer="", evidence=evidence)
        return AssistantEnvelope(
            status="clarify",
            answer="",
            clarifying_question=_single_sentence(question),
            options=options[:MAX_OPTIONS],
            evidence=evidence,
        )

    if status == "unknown":
        return AssistantEnvelope(status="unknown", answer=answer, evidence=evidence)

    return AssistantEnvelope(status="answer", answer=answer or question, evidence=evidence)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _options(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        option = item.strip()
        if option and option not in seen:
            seen.append(option)
    return seen[:MAX_OPTIONS]


def _evidence(value: object) -> list[EvidenceRef]:
    if not isinstance(value, list):
        return []
    refs: list[EvidenceRef] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in ("citation", "tool", "db"):
            kind = "citation"
        index = item.get("index")
        refs.append(
            EvidenceRef(
                kind=kind,
                index=index if isinstance(index, int) and index >= 0 else None,
                label=_text(item.get("label")) or None,
            )
        )
    return refs


def _single_sentence(question: str) -> str:
    """Keep one question mark of text: extra sentences are dropped, not merged."""
    parts = re.split(r"(?<=[?])\s+", question.strip(), maxsplit=1)
    return parts[0].strip()
