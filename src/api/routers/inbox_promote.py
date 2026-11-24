from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_embedding_provider, get_principal
from modules.channels.repository import ChannelNotFoundError, ChannelRepository
from modules.conversations.models import ConversationMessage
from modules.identity.principal import Principal
from modules.knowledge.repository import DuplicateDocumentError, KnowledgeRepository
from modules.model_gateway.embeddings import EmbeddingProvider

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


class PromoteKBOut(BaseModel):
    document_id: str
    title: str
    status: str


@router.post(
    "/sessions/{session_id}/messages/{message_id}/promote-kb",
    response_model=PromoteKBOut,
    status_code=status.HTTP_201_CREATED,
)
async def promote_reply_to_kb(
    session_id: str,
    message_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> PromoteKBOut:
    """Closed-loop learning: promote a human agent reply + user question into tenant KB."""
    try:
        ch_session = await ChannelRepository(session).get_session_for_tenant(
            session_id, principal.tenant_id
        )
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == ch_session.conversation_id)
        .order_by(ConversationMessage.created_at.asc())
    )
    messages = list((await session.execute(stmt)).scalars().all())
    target_idx = next((i for i, m in enumerate(messages) if m.id == message_id), None)
    if target_idx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")

    answer_msg = messages[target_idx]
    question_text = ""
    for prev in reversed(messages[:target_idx]):
        if prev.role == "user":
            question_text = prev.content
            break

    title = f"FAQ: {question_text[:80]}" if question_text else f"FAQ Inbox {message_id[:8]}"
    content = (
        f"Pertanyaan: {question_text}\nJawaban: {answer_msg.content}"
        if question_text
        else answer_msg.content
    )
    kb_repo = KnowledgeRepository(
        session=session,
        embedding_provider=embeddings,
        principal=principal,
    )
    try:
        doc = await kb_repo.ingest_document(
            title=title,
            content=content,
            source="inbox_handover",
            visibility="tenant",
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="FAQ serupa sudah ada di Knowledge Base.",
        ) from exc

    return PromoteKBOut(document_id=doc.id, title=doc.title, status="indexed")
