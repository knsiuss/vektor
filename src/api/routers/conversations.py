from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session
from modules.conversations.repository import ConversationRepository
from modules.conversations.schemas import ConversationDetail, ConversationSummary

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def _get_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationRepository:
    return ConversationRepository(session=session)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    repo: Annotated[ConversationRepository, Depends(_get_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConversationSummary]:
    """List recent conversation threads ordered by most recently updated."""
    conversations = await repo.list_conversations(limit=limit, offset=offset)
    return [ConversationSummary.model_validate(item) for item in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    repo: Annotated[ConversationRepository, Depends(_get_repository)],
) -> ConversationDetail:
    """Retrieve a single conversation thread and its ordered message history."""
    conversation = await repo.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    return ConversationDetail.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    repo: Annotated[ConversationRepository, Depends(_get_repository)],
) -> Response:
    """Delete a conversation thread and all of its persisted messages."""
    deleted = await repo.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
