from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ChatServiceFactory,
    get_chat_service_factory,
    get_db_session,
    get_session_factory,
)
from api.streaming import stream_events
from modules.ai_runtime.pii import PIIScrubber
from modules.ai_runtime.schemas import ChatTurnInput
from modules.identity.principal import Principal
from modules.usage.budget import BudgetExceededError, BudgetRepository
from modules.usage.recorder import UsageRecorder
from modules.widgets.models import ChatWidget, VisitorSession
from modules.widgets.repository import (
    WidgetNotFoundError,
    WidgetRepository,
    is_origin_allowed,
    visitor_owner_id,
)
from modules.widgets.schemas import PublicChatInput, WidgetPublicConfig

router = APIRouter(prefix="/api/v1/public/widgets", tags=["public-widgets"])
_pii_scrubber = PIIScrubber()


@dataclass(frozen=True)
class _VisitorContext:
    widget: ChatWidget
    visitor_session: VisitorSession
    recorder: UsageRecorder


def _check_origin(request: Request, widget: ChatWidget) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not is_origin_allowed(origin, widget.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin is not allowed for this widget.",
        )


async def _resolve_visitor_context(
    public_key: str,
    payload: PublicChatInput,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> _VisitorContext:
    """Resolve widget, origin, visitor session, principal, and tenant budget before ChatService."""
    repo = WidgetRepository(session)
    try:
        widget = await repo.get_by_public_key(public_key)
    except WidgetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _check_origin(request, widget)

    visitor_session = await repo.get_or_create_visitor_session(widget, payload.visitor_token)
    visitor_principal = Principal(
        user_id=visitor_owner_id(visitor_session.visitor_token_hash),
        tenant_id=widget.tenant_id,
        roles=frozenset({"member"}),
    )
    request.state.principal = visitor_principal

    try:
        await BudgetRepository(session, visitor_principal).ensure_within_budget()
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tenant usage budget exceeded.",
        ) from exc

    recorder = UsageRecorder(
        session_factory=get_session_factory(request),
        principal=visitor_principal,
    )
    request.state.usage_recorder = recorder
    return _VisitorContext(widget=widget, visitor_session=visitor_session, recorder=recorder)


@router.get("/{public_key}/config", response_model=WidgetPublicConfig)
async def get_public_widget_config(
    public_key: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WidgetPublicConfig:
    try:
        widget = await WidgetRepository(session).get_by_public_key(public_key)
    except WidgetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _check_origin(request, widget)
    return WidgetPublicConfig(
        name=widget.name,
        welcome_message=widget.welcome_message,
        theme=widget.theme,
    )


@router.post("/{public_key}/chat/stream")
async def stream_public_widget_chat(
    payload: PublicChatInput,
    request: Request,
    ctx: Annotated[_VisitorContext, Depends(_resolve_visitor_context)],
    service_factory: Annotated[ChatServiceFactory, Depends(get_chat_service_factory)],
) -> StreamingResponse:
    sanitized_message = _pii_scrubber.redact(payload.message).sanitized
    turn_input = ChatTurnInput(
        message=sanitized_message,
        conversation_id=ctx.visitor_session.conversation_id,
        document_ids=ctx.widget.knowledge_scope,
        enable_tools=False,
        allow_mutating_tools=False,
    )

    async def _events() -> AsyncIterator[str]:
        async with get_session_factory(request)() as stream_session:
            async for frame in stream_events(
                service=service_factory(stream_session),
                session=stream_session,
                payload=turn_input,
                recorder=ctx.recorder,
            ):
                yield frame

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
