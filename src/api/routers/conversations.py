from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    get_conversation_compactor,
    get_db_session,
    get_principal,
    get_settings,
)
from core.config.settings import Settings
from modules.conversations.compaction import ConversationCompactor
from modules.conversations.context import build_conversation_detail
from modules.conversations.repository import ConversationNotFoundError, ConversationRepository
from modules.conversations.schemas import ConversationDetail, ConversationSummary
from modules.identity.principal import Principal
from modules.model_gateway.exceptions import ModelGatewayError

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def _get_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ConversationRepository:
    return ConversationRepository(session=session, principal=principal)


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
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationDetail:
    """Retrieve a single conversation thread, its messages, and prompt-window usage."""
    conversation = await repo.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    return build_conversation_detail(
        conversation,
        max_messages=settings.agent_max_history_messages,
        max_tokens=settings.agent_max_history_tokens,
    )


@router.post("/{conversation_id}/compact", response_model=ConversationDetail)
async def compact_conversation(
    conversation_id: str,
    compactor: Annotated[ConversationCompactor, Depends(get_conversation_compactor)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationDetail:
    """Summarize older turns into one message so the next prompt carries less history."""
    try:
        conversation = await compactor.compact(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream LLM provider failed to summarize the conversation.",
        ) from exc
    return build_conversation_detail(
        conversation,
        max_messages=settings.agent_max_history_messages,
        max_tokens=settings.agent_max_history_tokens,
    )


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
