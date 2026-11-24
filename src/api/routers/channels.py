from typing import Annotated, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal, get_settings
from core.config.settings import Settings
from modules.channels.models import ChannelConnector
from modules.channels.repository import ChannelNotFoundError, ChannelRepository
from modules.channels.schemas import ChannelCreate, ChannelResponse
from modules.channels.security import decrypt_channel_config
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


class TelegramSetupIn(BaseModel):
    public_base_url: HttpUrl


def _master_key(settings: Settings) -> str:
    return settings.kms_master_key.get_secret_value() if settings.kms_master_key else ""


def _webhook_path(connector: ChannelConnector) -> str:
    route_type = (
        "whatsapp"
        if connector.channel_type.startswith("whatsapp")
        else connector.channel_type
    )
    return f"/api/v1/public/channels/{route_type}/{connector.id}/webhook"


def _to_response(connector: ChannelConnector) -> ChannelResponse:
    return ChannelResponse(
        id=connector.id,
        tenant_id=connector.tenant_id,
        channel_type=connector.channel_type,
        name=connector.name,
        webhook_path=_webhook_path(connector),
        has_credentials=bool(connector.config),
        system_prompt=connector.system_prompt,
        auto_handover_threshold=connector.auto_handover_threshold,
        knowledge_scope=connector.knowledge_scope,
        is_active=connector.is_active,
        created_at=connector.created_at,
    )


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: ChannelCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChannelResponse:
    connector = await ChannelRepository(session).create(
        principal.tenant_id,
        payload,
        master_key=_master_key(settings),
    )
    return _to_response(connector)


@router.get("", response_model=list[ChannelResponse])
async def list_channels(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ChannelResponse]:
    connectors = await ChannelRepository(session).list_for_tenant(principal.tenant_id)
    return [_to_response(c) for c in connectors]


@router.post("/{connector_id}/telegram/setup")
async def setup_telegram_webhook(
    connector_id: str,
    payload: TelegramSetupIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """One-click Telegram Bot API setWebhook registration with secret_token."""
    try:
        connector = await ChannelRepository(session).get_for_tenant(
            connector_id, principal.tenant_id
        )
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if connector.channel_type != "telegram":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not a Telegram bot.")

    cfg = decrypt_channel_config(
        connector.config,
        master_key=_master_key(settings),
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
    )
    bot_token = cfg.get("bot_token", "")
    if not bot_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing bot_token.")

    webhook_url = f"{str(payload.public_base_url).rstrip('/')}{_webhook_path(connector)}"
    client = cast(httpx.AsyncClient, request.app.state.http_client)
    res = await client.post(
        f"https://api.telegram.org/bot{bot_token}/setWebhook",
        json={"url": webhook_url, "secret_token": connector.webhook_secret},
        timeout=15.0,
    )
    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram setWebhook call failed.",
        )
    return {"status": "configured", "webhook_url": webhook_url}


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    connector_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    try:
        await ChannelRepository(session).delete(connector_id, principal.tenant_id)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
