import base64
import hashlib
from itertools import cycle

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.settings.profile_models import ProviderProfile


def _key_stream(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def protect_secret(raw: str, *, app_secret: str) -> str:
    """Obfuscate an API key at rest using a deployment-scoped key stream."""
    mask = _key_stream(app_secret)
    data = raw.encode("utf-8")
    xored = bytes(b ^ m for b, m in zip(data, cycle(mask)))
    return base64.urlsafe_b64encode(xored).decode("ascii")


def reveal_secret(protected: str | None, *, app_secret: str) -> str | None:
    if not protected:
        return None
    mask = _key_stream(app_secret)
    raw = base64.urlsafe_b64decode(protected.encode("ascii"))
    plain = bytes(b ^ m for b, m in zip(raw, cycle(mask)))
    return plain.decode("utf-8")


class ProviderProfileIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    provider: str = Field(..., min_length=1, max_length=32)
    model: str = Field(..., min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    is_default: bool = False


class ProviderProfileOut(BaseModel):
    id: str
    label: str
    provider: str
    model: str
    base_url: str | None = None
    api_key_configured: bool
    is_default: bool


class ProviderProfileRepository:
    """Tenant- and user-scoped CRUD for multiple saved AI provider APIs."""

    def __init__(self, session: AsyncSession, *, app_secret: str = "vektor-local") -> None:
        self._session = session
        self._secret = app_secret

    async def list_profiles(self, *, tenant_id: str, user_id: str) -> list[ProviderProfileOut]:
        stmt = (
            select(ProviderProfile)
            .where(
                ProviderProfile.tenant_id == tenant_id,
                ProviderProfile.user_id == user_id,
            )
            .order_by(ProviderProfile.is_default.desc(), ProviderProfile.created_at.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_out(r) for r in rows]

    async def get_profile(
        self,
        *,
        profile_id: str,
        tenant_id: str,
        user_id: str,
    ) -> ProviderProfile | None:
        stmt = select(ProviderProfile).where(
            ProviderProfile.id == profile_id,
            ProviderProfile.tenant_id == tenant_id,
            ProviderProfile.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_profile(
        self,
        *,
        tenant_id: str,
        user_id: str,
        payload: ProviderProfileIn,
    ) -> ProviderProfileOut:
        if payload.is_default:
            await self._clear_defaults(tenant_id=tenant_id, user_id=user_id)
        record = ProviderProfile(
            tenant_id=tenant_id,
            user_id=user_id,
            label=payload.label.strip(),
            provider=payload.provider.strip(),
            model=payload.model.strip(),
            base_url=payload.base_url.strip() if payload.base_url else None,
            api_key_encrypted=(
                protect_secret(payload.api_key.strip(), app_secret=self._secret)
                if payload.api_key and payload.api_key.strip()
                else None
            ),
            is_default=payload.is_default,
        )
        self._session.add(record)
        await self._session.flush()
        return self._to_out(record)

    async def delete_profile(self, *, profile_id: str, tenant_id: str, user_id: str) -> bool:
        record = await self.get_profile(
            profile_id=profile_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if record is None:
            return False
        await self._session.delete(record)
        await self._session.flush()
        return True

    def decrypt_key(self, record: ProviderProfile) -> str | None:
        return reveal_secret(record.api_key_encrypted, app_secret=self._secret)

    async def _clear_defaults(self, *, tenant_id: str, user_id: str) -> None:
        stmt = select(ProviderProfile).where(
            ProviderProfile.tenant_id == tenant_id,
            ProviderProfile.user_id == user_id,
            ProviderProfile.is_default.is_(True),
        )
        for row in (await self._session.execute(stmt)).scalars().all():
            row.is_default = False

    @staticmethod
    def _to_out(record: ProviderProfile) -> ProviderProfileOut:
        return ProviderProfileOut(
            id=record.id,
            label=record.label,
            provider=record.provider,
            model=record.model,
            base_url=record.base_url,
            api_key_configured=bool(record.api_key_encrypted),
            is_default=record.is_default,
        )
