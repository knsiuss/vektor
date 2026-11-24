from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ChatServiceFactory,
    get_chat_service,
    get_chat_service_factory,
    get_db_session,
    get_principal,
    get_session_factory,
    get_usage_recorder,
    require_budget,
)
from api.streaming import stream_events
from modules.ai_runtime.schemas import ChatTurnInput, ChatTurnResult
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationNotFoundError, ConversationRepository
from modules.identity.principal import Principal
from modules.model_gateway.exceptions import (
    ModelGatewayError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from modules.usage.recorder import UsageRecorder
from modules.usage.repository import UsageEventRepository
from modules.usage.schemas import BudgetStatus, FeedbackInput, FeedbackResponse

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("", response_model=ChatTurnResult)
async def create_chat_turn(
    payload: ChatTurnInput,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    budget: Annotated[BudgetStatus, Depends(require_budget)],
) -> ChatTurnResult:
    """Execute a single or multi-turn conversational request."""
    del budget  # The dependency only exists to reject exhausted tenants.
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
    request: Request,
    service_factory: Annotated[ChatServiceFactory, Depends(get_chat_service_factory)],
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
    budget: Annotated[BudgetStatus, Depends(require_budget)],
) -> StreamingResponse:
    """Stream conversational chunks over Server-Sent Events and persist the turn.

    The stream owns its database session: a request-scoped dependency session may already be
    closed by the time the response body is produced. If the reader disconnects (Stop), the
    answer text sent so far is saved with a "stopped" marker.
    """

    async def _events() -> AsyncIterator[str]:
        async with get_session_factory(request)() as session:
            async for frame in stream_events(
                service=service_factory(session),
                session=session,
                payload=payload,
                recorder=recorder,
            ):
                yield frame

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackInput,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> FeedbackResponse:
    """Record a thumbs up/down on one of the caller's own assistant answers."""
    conversation = await ConversationRepository(
        session=session, principal=principal
    ).get_conversation(payload.conversation_id)
    if conversation is None or not any(
        message.id == payload.message_id for message in conversation.messages
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That message is not part of a conversation you can read.",
        )

    return await UsageEventRepository(session=session, principal=principal).record_feedback(
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        rating=payload.rating,
        comment=payload.comment,
    )
