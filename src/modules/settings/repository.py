"""Persistence for per-user AI provider settings."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.identity.principal import hash_api_key
from modules.settings.models import ProviderSetting


class ProviderSettingRepository:
    """CRUD for provider settings, scoped to a single tenant/user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, tenant_id: str, user_id: str) -> ProviderSetting | None:
        stmt = select(ProviderSetting).where(
            ProviderSetting.tenant_id == tenant_id,
            ProviderSetting.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        tenant_id: str,
        user_id: str,
        provider: str,
        model: str | None,
        api_key: str | None,
        base_url: str | None,
        connection_status: str,
        connection_error: str | None = None,
        latency_ms: int | None = None,
    ) -> ProviderSetting:
        record = await self.get(tenant_id=tenant_id, user_id=user_id)
        now = datetime.now(UTC)
        if record is None:
            record = ProviderSetting(
                tenant_id=tenant_id,
                user_id=user_id,
                provider=provider,
                model=model,
                api_key_hash=hash_api_key(api_key) if api_key else None,
                base_url=base_url,
                connection_status=connection_status,
                connection_error=connection_error,
                last_checked_at=now,
                latency_ms=latency_ms,
            )
            self._session.add(record)
        else:
            record.provider = provider
            record.model = model
            if api_key is not None:
                record.api_key_hash = hash_api_key(api_key) if api_key else None
            record.base_url = base_url
            record.connection_status = connection_status
            record.connection_error = connection_error
            record.last_checked_at = now
            record.latency_ms = latency_ms
        await self._session.flush()
        return record

    async def clear_api_key(self, *, tenant_id: str, user_id: str) -> bool:
        record = await self.get(tenant_id=tenant_id, user_id=user_id)
        if record is None or record.api_key_hash is None:
            return False
        record.api_key_hash = None
        record.connection_status = "disconnected"
        record.connection_error = None
        record.last_checked_at = datetime.now(UTC)
        await self._session.flush()
        return True
