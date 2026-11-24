"""Messaging gateway webhook adapter (Telegram, Slack, Discord, generic)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session, get_principal
from modules.ai_runtime.schemas import ChatTurnInput
from modules.ai_runtime.service import ChatService
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/gateway", tags=["gateway"])


class GatewayMessageIn(BaseModel):
    """Normalized inbound message from an external chat channel."""

    channel: Literal["telegram", "slack", "discord", "webhook"] = "webhook"
    sender_id: str = Field(..., min_length=1, max_length=128)
    text: str = Field(..., min_length=1, max_length=8000)
    conversation_id: str | None = None
    allow_mutating_tools: bool = False


class GatewayMessageOut(BaseModel):
    """Normalized outbound reply for the messaging channel."""

    channel: str
    conversation_id: str
    reply: str
    model: str
    citations_count: int


@router.post("/webhook", response_model=GatewayMessageOut)
async def handle_gateway_message(
    payload: GatewayMessageIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> GatewayMessageOut:
    """Route an inbound messaging gateway turn through Vektor's ChatService."""
    _ = principal
    result = await chat_service.execute_turn(
        ChatTurnInput(
            conversation_id=payload.conversation_id,
            message=payload.text,
            allow_mutating_tools=payload.allow_mutating_tools,
        )
    )
    await session.commit()
    return GatewayMessageOut(
        channel=payload.channel,
        conversation_id=result.conversation_id,
        reply=result.reply,
        model=result.model,
        citations_count=len(result.citations),
    )
