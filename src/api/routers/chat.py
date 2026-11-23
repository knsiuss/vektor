from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_chat_service
from modules.ai_runtime.schemas import ChatTurnInput, ChatTurnResult
from modules.ai_runtime.service import ChatService
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
    """Execute a single conversational turn with the configured AI runtime."""
    try:
        return await chat_service.execute_turn(payload)
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
