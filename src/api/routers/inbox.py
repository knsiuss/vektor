from datetime import datetime
from typing import Annotated, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal, get_settings
from core.config.settings import Settings
from modules.channels.adapters import (
    send_telegram_reply,
    send_whatsapp_cloud_reply,
    send_whatsapp_qr_reply,
)
from modules.channels.event_bus import inbox_event_bus
from modules.channels.repository import ChannelNotFoundError, ChannelRepository
from modules.channels.security import decrypt_channel_config
from modules.conversations.models import ConversationMessage
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


class InboxSessionOut(BaseModel):
    id: str
    connector_id: str
    external_user_id: str
    conversation_id: str
    handover_mode: bool
    unknown_streak: int
    assigned_agent_id: str | None
    last_active_at: datetime


class HandoverToggleIn(BaseModel):
    handover_mode: bool


class InboxMessageOut(BaseModel):
    id: str
    role: str
    content: str
    provider: str | None
    created_at: datetime


class ManualReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.get("/sessions", response_model=list[InboxSessionOut])
async def list_inbox_sessions(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[InboxSessionOut]:
    rows = await ChannelRepository(session).list_sessions_for_tenant(principal.tenant_id)
    return [
        InboxSessionOut(
            id=r.id,
            connector_id=r.connector_id,
            external_user_id=r.external_user_id,
            conversation_id=r.conversation_id,
            handover_mode=r.handover_mode,
            unknown_streak=r.unknown_streak,
            assigned_agent_id=r.assigned_agent_id,
            last_active_at=r.last_active_at,
        )
        for r in rows
    ]


@router.patch("/sessions/{session_id}/handover", response_model=InboxSessionOut)
async def toggle_handover(
    session_id: str,
    payload: HandoverToggleIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> InboxSessionOut:
    """Switch a channel conversation between AI auto-reply and human handover."""
    try:
        row = await ChannelRepository(session).set_handover_mode(
            session_id, principal.tenant_id, payload.handover_mode
        )
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return InboxSessionOut(
        id=row.id,
        connector_id=row.connector_id,
        external_user_id=row.external_user_id,
        conversation_id=row.conversation_id,
        handover_mode=row.handover_mode,
        unknown_streak=row.unknown_streak,
        assigned_agent_id=row.assigned_agent_id,
        last_active_at=row.last_active_at,
    )


@router.get("/sessions/{session_id}/messages", response_model=list[InboxMessageOut])
async def list_session_messages(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[InboxMessageOut]:
    try:
        row = await ChannelRepository(session).get_session_for_tenant(
            session_id, principal.tenant_id
        )
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == row.conversation_id)
        .order_by(ConversationMessage.created_at.asc())
        .limit(200)
    )
    messages = list((await session.execute(stmt)).scalars().all())
    return [
        InboxMessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            provider=m.provider,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/sessions/{session_id}/reply", response_model=InboxMessageOut)
async def send_manual_reply(
    session_id: str,
    payload: ManualReplyIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboxMessageOut:
    """Persist a human agent reply and deliver it to the external channel."""
    repo = ChannelRepository(session)
    try:
        row = await repo.get_session_for_tenant(session_id, principal.tenant_id)
        connector = await repo.get_for_tenant(row.connector_id, principal.tenant_id)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    msg = ConversationMessage(
        conversation_id=row.conversation_id,
        role="assistant",
        content=payload.message,
        provider="human",
        model="agent",
    )
    session.add(msg)
    await session.flush()
    await session.refresh(msg)
    await inbox_event_bus.publish(
        principal.tenant_id,
        "inbox.message",
        {"session_id": row.id, "role": "assistant"},
    )

    master_key = settings.kms_master_key.get_secret_value() if settings.kms_master_key else ""
    cfg = decrypt_channel_config(
        connector.config,
        master_key=master_key,
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
    )
    http_client = cast(httpx.AsyncClient, request.app.state.http_client)
    if connector.channel_type == "telegram" and cfg.get("bot_token"):
        await send_telegram_reply(
            http_client,
            cfg["bot_token"],
            row.external_user_id,
            payload.message,
        )
    elif connector.channel_type == "whatsapp_qr" and cfg.get("bridge_url"):
        await send_whatsapp_qr_reply(
            http_client,
            cfg["bridge_url"],
            cfg.get("api_key", ""),
            row.external_user_id,
            payload.message,
        )
    elif (
        connector.channel_type == "whatsapp_cloud"
        and cfg.get("phone_number_id")
        and cfg.get("access_token")
    ):
        await send_whatsapp_cloud_reply(
            http_client,
            cfg["phone_number_id"],
            cfg["access_token"],
            row.external_user_id,
            payload.message,
        )

    return InboxMessageOut(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        provider=msg.provider,
        created_at=msg.created_at,
    )
