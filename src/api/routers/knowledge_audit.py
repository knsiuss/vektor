from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.identity.principal import Principal
from modules.knowledge.freshness_audit import DocumentSummary, audit_knowledge_documents
from modules.knowledge.models import KnowledgeDocument

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


class ConflictOut(BaseModel):
    doc_a_id: str
    doc_a_title: str
    doc_b_id: str
    doc_b_title: str
    similarity: float


class KnowledgeAuditOut(BaseModel):
    total_documents: int
    stale_doc_ids: list[str]
    conflicts: list[ConflictOut]


@router.get("/audit", response_model=KnowledgeAuditOut)
async def get_knowledge_audit(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    ttl_days: int = Query(90, ge=1, le=3650),
) -> KnowledgeAuditOut:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == principal.tenant_id)
    rows = list((await session.execute(stmt)).scalars().all())
    summaries = [
        DocumentSummary(id=r.id, title=r.title, updated_at=r.last_synced_at) for r in rows
    ]
    report = audit_knowledge_documents(summaries, freshness_ttl_days=ttl_days)
    return KnowledgeAuditOut(
        total_documents=len(rows),
        stale_doc_ids=report.stale_doc_ids,
        conflicts=[
            ConflictOut(
                doc_a_id=c.doc_a_id,
                doc_a_title=c.doc_a_title,
                doc_b_id=c.doc_b_id,
                doc_b_title=c.doc_b_title,
                similarity=c.similarity,
            )
            for c in report.conflicts
        ],
    )
