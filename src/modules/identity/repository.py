from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.identity.models import ApiKey, AuditLog
from modules.identity.principal import ROLE_MEMBER, VALID_ROLES


def parse_roles(raw: str) -> frozenset[str]:
    """Parse a comma-separated role string, ignoring unknown roles (default: member)."""
    roles = frozenset(item.strip() for item in raw.split(",") if item.strip()) & VALID_ROLES
    return roles or frozenset({ROLE_MEMBER})


class ApiKeyRepository:
    """Persistence for per-user API keys (hash-only)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_active(self, key_hash: str) -> ApiKey | None:
        """Return the key row if it exists, is not revoked and has not expired."""
        now = datetime.now(UTC)
        stmt = select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked_at.is_(None),
            or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def has_any_active(self) -> bool:
        """Report whether any usable key exists, i.e. authentication is configured."""
        now = datetime.now(UTC)
        stmt = select(ApiKey.id).where(
            ApiKey.revoked_at.is_(None),
            or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
        ).limit(1)
        return (await self._session.execute(stmt)).first() is not None

    async def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        key_hash: str,
        roles: str,
        label: str | None,
        expires_at: datetime | None,
    ) -> ApiKey:
        record = ApiKey(
            tenant_id=tenant_id,
            user_id=user_id,
            key_hash=key_hash,
            roles=",".join(sorted(parse_roles(roles))),
            label=label,
            expires_at=expires_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def revoke(self, key_id: str) -> bool:
        record = (
            await self._session.execute(select(ApiKey).where(ApiKey.id == key_id))
        ).scalar_one_or_none()
        if record is None:
            return False
        if record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
            await self._session.flush()
        return True

    async def list_keys(self, *, tenant_id: str | None = None) -> list[ApiKey]:
        stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
        if tenant_id:
            stmt = stmt.where(ApiKey.tenant_id == tenant_id)
        return list((await self._session.execute(stmt)).scalars().all())


class AuditRepository:
    """Read access to the audit log, always scoped to a single tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())
