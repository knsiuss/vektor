from datetime import UTC, datetime
from fnmatch import fnmatch
from hashlib import sha256
from secrets import token_hex
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.conversations.models import Conversation
from modules.widgets.models import ChatWidget, VisitorSession
from modules.widgets.schemas import WidgetCreate, WidgetUpdate


class WidgetNotFoundError(Exception):
    """Raised when a requested widget does not exist or is inaccessible."""


def _generate_public_key() -> str:
    return f"vwk_{token_hex(16)}"


def hash_visitor_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def visitor_owner_id(token_hash: str) -> str:
    return f"visitor:{token_hash[:16]}"


def _extract_hostname(origin: str) -> str:
    cleaned = origin.strip()
    if "://" not in cleaned:
        cleaned = f"http://{cleaned}"
    return (urlparse(cleaned).hostname or "").lower().strip()


def is_origin_allowed(origin: str | None, allowed_domains: list[str]) -> bool:
    """Validate request Origin/Referer hostname against widget allowed_domains."""
    if not allowed_domains:
        return True
    if not origin:
        return False

    hostname = _extract_hostname(origin)
    if not hostname:
        return False

    for pattern in allowed_domains:
        normalized = pattern.lower().strip()
        if not normalized:
            continue
        if normalized == hostname:
            return True
        if normalized.startswith("*.") and fnmatch(hostname, normalized):
            return True
    return False


class WidgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, tenant_id: str, payload: WidgetCreate) -> ChatWidget:
        widget = ChatWidget(
            tenant_id=tenant_id,
            public_key=_generate_public_key(),
            name=payload.name,
            allowed_domains=payload.allowed_domains,
            system_prompt=payload.system_prompt,
            welcome_message=payload.welcome_message,
            theme=payload.theme,
            knowledge_scope=payload.knowledge_scope,
        )
        self._session.add(widget)
        await self._session.flush()
        await self._session.refresh(widget)
        return widget

    async def list_for_tenant(self, tenant_id: str) -> list[ChatWidget]:
        stmt = (
            select(ChatWidget)
            .where(ChatWidget.tenant_id == tenant_id)
            .order_by(ChatWidget.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, widget_id: str, tenant_id: str) -> ChatWidget:
        stmt = select(ChatWidget).where(
            ChatWidget.id == widget_id,
            ChatWidget.tenant_id == tenant_id,
        )
        widget = (await self._session.execute(stmt)).scalar_one_or_none()
        if widget is None:
            raise WidgetNotFoundError(f"Widget {widget_id} not found.")
        return widget

    async def get_by_public_key(self, public_key: str) -> ChatWidget:
        stmt = select(ChatWidget).where(
            ChatWidget.public_key == public_key,
            ChatWidget.is_active.is_(True),
        )
        widget = (await self._session.execute(stmt)).scalar_one_or_none()
        if widget is None:
            raise WidgetNotFoundError("Widget not found or inactive.")
        return widget

    async def update(self, widget_id: str, tenant_id: str, payload: WidgetUpdate) -> ChatWidget:
        widget = await self.get_by_id(widget_id, tenant_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(widget, field, value)
        await self._session.flush()
        await self._session.refresh(widget)
        return widget

    async def delete(self, widget_id: str, tenant_id: str) -> None:
        widget = await self.get_by_id(widget_id, tenant_id)
        await self._session.delete(widget)
        await self._session.flush()

    async def get_or_create_visitor_session(
        self,
        widget: ChatWidget,
        visitor_token: str,
    ) -> VisitorSession:
        token_hash = hash_visitor_token(visitor_token)
        stmt = select(VisitorSession).where(
            VisitorSession.widget_id == widget.id,
            VisitorSession.visitor_token_hash == token_hash,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.last_active_at = datetime.now(UTC)
            await self._session.flush()
            return existing

        conversation = Conversation(
            title=f"Widget: {widget.name}",
            tenant_id=widget.tenant_id,
            owner_id=visitor_owner_id(token_hash),
        )
        self._session.add(conversation)
        await self._session.flush()

        session_row = VisitorSession(
            widget_id=widget.id,
            tenant_id=widget.tenant_id,
            visitor_token_hash=token_hash,
            conversation_id=conversation.id,
        )
        self._session.add(session_row)
        await self._session.flush()
        await self._session.refresh(session_row)
        return session_row
