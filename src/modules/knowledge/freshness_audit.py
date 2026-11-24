from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher


@dataclass(frozen=True)
class DocumentSummary:
    id: str
    title: str
    updated_at: datetime


@dataclass(frozen=True)
class ConflictCandidate:
    doc_a_id: str
    doc_a_title: str
    doc_b_id: str
    doc_b_title: str
    similarity: float


@dataclass(frozen=True)
class KnowledgeAuditReport:
    stale_doc_ids: list[str]
    conflicts: list[ConflictCandidate]


def _normalize_title(title: str) -> str:
    return " ".join(title.lower().replace("-", " ").replace("_", " ").split())


def audit_knowledge_documents(
    docs: list[DocumentSummary],
    *,
    freshness_ttl_days: int = 90,
    conflict_threshold: float = 0.72,
    now: datetime | None = None,
) -> KnowledgeAuditReport:
    """Detect stale documents past TTL and near-duplicate titles that risk policy conflict."""
    ref_time = now or datetime.now(UTC)
    cutoff = ref_time - timedelta(days=freshness_ttl_days)
    stale_ids: list[str] = []
    for doc in docs:
        ts = doc.updated_at if doc.updated_at.tzinfo else doc.updated_at.replace(tzinfo=UTC)
        if ts < cutoff:
            stale_ids.append(doc.id)

    conflicts: list[ConflictCandidate] = []
    normalized = [(d, _normalize_title(d.title)) for d in docs]
    for i in range(len(normalized)):
        doc_a, title_a = normalized[i]
        for j in range(i + 1, len(normalized)):
            doc_b, title_b = normalized[j]
            ratio = SequenceMatcher(None, title_a, title_b).ratio()
            if ratio >= conflict_threshold:
                conflicts.append(
                    ConflictCandidate(
                        doc_a_id=doc_a.id,
                        doc_a_title=doc_a.title,
                        doc_b_id=doc_b.id,
                        doc_b_title=doc_b.title,
                        similarity=round(ratio, 3),
                    )
                )

    return KnowledgeAuditReport(stale_doc_ids=stale_ids, conflicts=conflicts)
