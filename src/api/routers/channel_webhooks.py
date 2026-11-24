import json
from secrets import compare_digest
from typing import Annotated, Any, cast

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ChatServiceFactory,
    get_chat_service_factory,
    get_db_session,
    get_session_factory,
    get_settings,
)
from core.config.settings import Settings
from modules.ai_runtime.pii import PIIScrubber
from modules.ai_runtime.schemas import ChatTurnInput
from modules.channels.adapters import (
    parse_discord_interaction,
    parse_telegram_update,
    parse_whatsapp_webhook,
    send_telegram_reply,
    send_whatsapp_cloud_reply,
    send_whatsapp_qr_reply,
)
from modules.channels.dedup import WebhookDeduplicator
from modules.channels.models import ChannelConnector
from modules.channels.repository import ChannelNotFoundError, ChannelRepository, channel_owner_id
from modules.channels.security import (
    decrypt_channel_config,
    verify_discord_signature,
    verify_meta_signature,
)
from modules.conversations.models import ConversationMessage
from modules.identity.principal import Principal
from modules.usage.budget import BudgetExceededError, BudgetRepository
from modules.usage.recorder import UsageRecorder

router = APIRouter(prefix="/api/v1/public/channels", tags=["channel-webhooks"])
_dedup = WebhookDeduplicator()
_pii_scrubber = PIIScrubber()


def _master_key(settings: Settings) -> str:
    return settings.kms_master_key.get_secret_value() if settings.kms_master_key else ""


async def _load_connector_for_webhook(
    connector_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChannelConnector:
    try:
        connector = await ChannelRepository(session).get_active(connector_id)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    presented = (
        request.headers.get("x-telegram-bot-api-secret-token")
        or request.query_params.get("secret")
        or ""
    )
    if connector.channel_type != "discord" and presented and not compare_digest(
        presented, connector.webhook_secret
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret.")

    principal = Principal(
        user_id=channel_owner_id(connector.channel_type, "webhook"),
        tenant_id=connector.tenant_id,
        roles=frozenset({"member"}),
    )
    request.state.principal = principal
    request.state.usage_recorder = UsageRecorder(get_session_factory(request), principal)
    return connector


async def _run_turn_if_not_handed_over(
    session: AsyncSession,
    connector: ChannelConnector,
    external_user_id: str,
    text: str,
    service_factory: ChatServiceFactory,
) -> str | None:
    principal = Principal(
        user_id=channel_owner_id(connector.channel_type, external_user_id),
        tenant_id=connector.tenant_id,
        roles=frozenset({"member"}),
    )
    channel_session = await ChannelRepository(session).get_or_create_session(
        connector, external_user_id
    )
    if channel_session.handover_mode:
        session.add(
            ConversationMessage(
                conversation_id=channel_session.conversation_id,
                role="user",
                content=text,
            )
        )
        await session.flush()
        return None
    try:
        await BudgetRepository(session, principal).ensure_within_budget()
    except BudgetExceededError:
        return "Maaf, kuota layanan sedang penuh. Silakan coba lagi nanti."

    sanitized_text = _pii_scrubber.redact(text).sanitized
    effective_msg = (
        f"[Persona: {connector.system_prompt}]\n\n{sanitized_text}"
        if connector.system_prompt
        else sanitized_text
    )
    turn_input = ChatTurnInput(
        message=effective_msg,
        conversation_id=channel_session.conversation_id,
        document_ids=connector.knowledge_scope,
        enable_tools=False,
        allow_mutating_tools=False,
    )
    result = await service_factory(session).execute_turn(turn_input)
    if result.status == "unknown":
        channel_session.unknown_streak += 1
        if (
            connector.auto_handover_threshold > 0
            and channel_session.unknown_streak >= connector.auto_handover_threshold
        ):
            channel_session.handover_mode = True
    else:
        channel_session.unknown_streak = 0
    await session.flush()
    return result.reply


async def _process_telegram_bg(
    request: Request,
    connector: ChannelConnector,
    cfg: dict[str, str],
    external_user_id: str,
    reply_target_id: str,
    text: str,
    service_factory: ChatServiceFactory,
) -> None:
    async with get_session_factory(request)() as bg_session:
        reply = await _run_turn_if_not_handed_over(
            bg_session, connector, external_user_id, text, service_factory
        )
        await bg_session.commit()
    bot_token = cfg.get("bot_token", "")
    if reply and bot_token:
        http_client = cast(httpx.AsyncClient, request.app.state.http_client)
        await send_telegram_reply(http_client, bot_token, reply_target_id, reply)


async def _process_whatsapp_bg(
    request: Request,
    connector: ChannelConnector,
    cfg: dict[str, str],
    external_user_id: str,
    reply_target_id: str,
    text: str,
    service_factory: ChatServiceFactory,
) -> None:
    async with get_session_factory(request)() as bg_session:
        reply = await _run_turn_if_not_handed_over(
            bg_session, connector, external_user_id, text, service_factory
        )
        await bg_session.commit()
    if not reply:
        return
    http_client = cast(httpx.AsyncClient, request.app.state.http_client)
    if connector.channel_type == "whatsapp_qr":
        if cfg.get("bridge_url"):
            await send_whatsapp_qr_reply(
                http_client, cfg["bridge_url"], cfg.get("api_key", ""), reply_target_id, reply
            )
    elif cfg.get("phone_number_id") and cfg.get("access_token"):
        await send_whatsapp_cloud_reply(
            http_client, cfg["phone_number_id"], cfg["access_token"], reply_target_id, reply
        )


@router.post("/telegram/{connector_id}/webhook")
async def telegram_webhook(
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
    connector: Annotated[ChannelConnector, Depends(_load_connector_for_webhook)],
    settings: Annotated[Settings, Depends(get_settings)],
    service_factory: Annotated[ChatServiceFactory, Depends(get_chat_service_factory)],
) -> dict[str, bool]:
    inbound = parse_telegram_update(payload)
    if inbound is None or not _dedup.mark_if_new(connector.id, inbound.external_event_id):
        return {"ok": True}
    cfg = decrypt_channel_config(
        connector.config,
        master_key=_master_key(settings),
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
    )
    background_tasks.add_task(
        _process_telegram_bg,
        request,
        connector,
        cfg,
        inbound.external_user_id,
        inbound.reply_target_id,
        inbound.text,
        service_factory,
    )
    return {"ok": True}


@router.get("/whatsapp/{connector_id}/webhook")
async def whatsapp_verify(
    connector_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    try:
        connector = await ChannelRepository(session).get_active(connector_id)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    expected = connector.config.get("verify_token", connector.webhook_secret)
    if hub_mode == "subscribe" and compare_digest(hub_verify_token, expected):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed.")


@router.post("/whatsapp/{connector_id}/webhook")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    connector: Annotated[ChannelConnector, Depends(_load_connector_for_webhook)],
    settings: Annotated[Settings, Depends(get_settings)],
    service_factory: Annotated[ChatServiceFactory, Depends(get_chat_service_factory)],
) -> dict[str, bool]:
    raw_body = await request.body()
    cfg = decrypt_channel_config(
        connector.config,
        master_key=_master_key(settings),
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
    )
    app_secret = cfg.get("app_secret", "")
    if app_secret and not verify_meta_signature(
        raw_body, request.headers.get("x-hub-signature-256"), app_secret
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Meta signature.")

    inbound = parse_whatsapp_webhook(cast(dict[str, Any], json.loads(raw_body)))
    if inbound is None or not _dedup.mark_if_new(connector.id, inbound.external_event_id):
        return {"ok": True}
    background_tasks.add_task(
        _process_whatsapp_bg,
        request,
        connector,
        cfg,
        inbound.external_user_id,
        inbound.reply_target_id,
        inbound.text,
        service_factory,
    )
    return {"ok": True}


@router.post("/discord/{connector_id}/webhook")
async def discord_webhook(
    request: Request,
    connector: Annotated[ChannelConnector, Depends(_load_connector_for_webhook)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    service_factory: Annotated[ChatServiceFactory, Depends(get_chat_service_factory)],
) -> dict[str, Any]:
    raw_body = await request.body()
    cfg = decrypt_channel_config(
        connector.config,
        master_key=_master_key(settings),
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
    )
    public_key = cfg.get("public_key", "")
    if public_key and not verify_discord_signature(
        raw_body,
        request.headers.get("x-signature-ed25519"),
        request.headers.get("x-signature-timestamp"),
        public_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Discord signature."
        )

    payload = cast(dict[str, Any], json.loads(raw_body))
    if payload.get("type") == 1:
        return {"type": 1}

    inbound = parse_discord_interaction(payload)
    if inbound is None or not _dedup.mark_if_new(connector.id, inbound.external_event_id):
        return {"type": 4, "data": {"content": "Silakan kirim pesan teks."}}

    reply = await _run_turn_if_not_handed_over(
        session, connector, inbound.external_user_id, inbound.text, service_factory
    )
    if reply is None:
        return {"type": 4, "data": {"content": "Pesan Anda sedang ditangani oleh tim kami."}}
    return {"type": 4, "data": {"content": reply[:2000]}}
