from datetime import UTC, datetime
from secrets import token_hex
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.channels.models import ChannelConnector, ChannelSession
from modules.channels.schemas import ChannelCreate
from modules.channels.security import encrypt_channel_config
from modules.conversations.models import Conversation


class ChannelNotFoundError(Exception):
    """Raised when a channel connector or session does not exist or is inactive."""


def channel_owner_id(channel_type: str, external_user_id: str) -> str:
    return f"{channel_type}:{external_user_id[:64]}"


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        tenant_id: str,
        payload: ChannelCreate,
        *,
        master_key: str = "",
    ) -> ChannelConnector:
        connector_id = str(uuid4())
        encrypted_cfg = encrypt_channel_config(
            payload.config,
            master_key=master_key,
            tenant_id=tenant_id,
            connector_id=connector_id,
        )
        connector = ChannelConnector(
            id=connector_id,
            tenant_id=tenant_id,
            channel_type=payload.channel_type,
            name=payload.name,
            webhook_secret=token_hex(24),
            config=encrypted_cfg,
            system_prompt=payload.system_prompt,
            auto_handover_threshold=payload.auto_handover_threshold,
            knowledge_scope=payload.knowledge_scope,
        )
        self._session.add(connector)
        await self._session.flush()
        await self._session.refresh(connector)
        return connector

    async def list_for_tenant(self, tenant_id: str) -> list[ChannelConnector]:
        stmt = (
            select(ChannelConnector)
            .where(ChannelConnector.tenant_id == tenant_id)
            .order_by(ChannelConnector.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_tenant(self, connector_id: str, tenant_id: str) -> ChannelConnector:
        stmt = select(ChannelConnector).where(
            ChannelConnector.id == connector_id,
            ChannelConnector.tenant_id == tenant_id,
        )
        connector = (await self._session.execute(stmt)).scalar_one_or_none()
        if connector is None:
            raise ChannelNotFoundError("Channel connector not found.")
        return connector

    async def get_active(self, connector_id: str) -> ChannelConnector:
        stmt = select(ChannelConnector).where(
            ChannelConnector.id == connector_id,
            ChannelConnector.is_active.is_(True),
        )
        connector = (await self._session.execute(stmt)).scalar_one_or_none()
        if connector is None:
            raise ChannelNotFoundError("Channel connector not found or inactive.")
        return connector

    async def delete(self, connector_id: str, tenant_id: str) -> None:
        connector = await self.get_for_tenant(connector_id, tenant_id)
        await self._session.delete(connector)
        await self._session.flush()

    async def get_or_create_session(
        self,
        connector: ChannelConnector,
        external_user_id: str,
    ) -> ChannelSession:
        stmt = select(ChannelSession).where(
            ChannelSession.connector_id == connector.id,
            ChannelSession.external_user_id == external_user_id,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.last_active_at = datetime.now(UTC)
            await self._session.flush()
            return existing

        conversation = Conversation(
            title=f"{connector.channel_type}: {external_user_id}",
            tenant_id=connector.tenant_id,
            owner_id=channel_owner_id(connector.channel_type, external_user_id),
        )
        self._session.add(conversation)
        await self._session.flush()

        row = ChannelSession(
            connector_id=connector.id,
            tenant_id=connector.tenant_id,
            external_user_id=external_user_id,
            conversation_id=conversation.id,
        )
        self._session.add(row)
    async def assign_agent(
        self,
        session_id: str,
        tenant_id: str,
        agent_id: str | None,
    ) -> ChannelSession:
        row = await self.get_session_for_tenant(session_id, tenant_id)
        row.assigned_agent_id = agent_id
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_sessions_for_tenant(self, tenant_id: str) -> list[ChannelSession]:
        stmt = (
            select(ChannelSession)
            .where(ChannelSession.tenant_id == tenant_id)
            .order_by(ChannelSession.last_active_at.desc())
            .limit(100)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_session_for_tenant(self, session_id: str, tenant_id: str) -> ChannelSession:
        stmt = select(ChannelSession).where(
            ChannelSession.id == session_id,
            ChannelSession.tenant_id == tenant_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChannelNotFoundError("Channel session not found.")
        return row

    async def set_handover_mode(
        self,
        session_id: str,
        tenant_id: str,
        handover_mode: bool,
    ) -> ChannelSession:
        row = await self.get_session_for_tenant(session_id, tenant_id)
        row.handover_mode = handover_mode
        if not handover_mode:
            row.unknown_streak = 0
    async def assign_agent(
        self,
        session_id: str,
        tenant_id: str,
        agent_id: str | None,
    ) -> ChannelSession:
        row = await self.get_session_for_tenant(session_id, tenant_id)
        row.assigned_agent_id = agent_id
        await self._session.flush()
        await self._session.refresh(row)
        return row
