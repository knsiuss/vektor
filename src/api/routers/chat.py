from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session
from modules.ai_runtime.schemas import ChatTurnInput, ChatTurnResult
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationNotFoundError
from modules.model_gateway.exceptions import (
    ModelGatewayError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("", response_model=ChatTurnResult)
async def create_chat_turn(
    payload: ChatTurnInput,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatTurnResult:
    """Execute a single or multi-turn conversational request."""
    try:
        return await chat_service.execute_turn(payload)
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM provider authentication is not properly configured.",
        ) from exc
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM provider rate limit exceeded. Please retry later.",
        ) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM provider request timed out.",
        ) from exc
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream LLM provider failed to fulfill the request.",
        ) from exc


@router.post("/stream")
async def stream_chat_turn(
    payload: ChatTurnInput,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    """Stream conversational chunks over Server-Sent Events and persist the turn."""

    async def _event_generator() -> AsyncIterator[str]:
        async for event in chat_service.stream_turn(payload):
            yield f"event: {event.event}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"
        await session.commit()

    return StreamingResponse(_event_generator(), media_type="text/event-stream")
