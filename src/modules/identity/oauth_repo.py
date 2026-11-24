"""Persistence for OAuth identities and browser sessions."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.identity.models import AuthSession, OAuthAccount
from modules.identity.oauth import OAuthProfile
from modules.identity.principal import DEFAULT_TENANT_ID, ROLE_MEMBER, Principal
from modules.identity.repository import parse_roles


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class OAuthRepository:
    """Links a provider identity to a user and issues opaque session tokens."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_account(self, profile: OAuthProfile) -> OAuthAccount:
        """Return the linked account, creating it on first login."""
        stmt = select(OAuthAccount).where(
            OAuthAccount.provider == profile.provider,
            OAuthAccount.provider_user_id == profile.provider_user_id,
        )
        record = (await self._session.execute(stmt)).scalar_one_or_none()
        now = datetime.now(UTC)
        if record is None:
            user_id = self._user_id(profile)
            record = OAuthAccount(
                provider=profile.provider,
                provider_user_id=profile.provider_user_id,
                user_id=user_id,
                tenant_id=DEFAULT_TENANT_ID,
                email=profile.email,
                name=profile.name,
                avatar_url=profile.avatar_url,
                roles=ROLE_MEMBER,
                last_login_at=now,
            )
            self._session.add(record)
        else:
            record.email = profile.email or record.email
            record.name = profile.name or record.name
            record.avatar_url = profile.avatar_url or record.avatar_url
            record.last_login_at = now
        await self._session.flush()
        return record

    def _user_id(self, profile: OAuthProfile) -> str:
        # Stable across logins, and unique per provider so two providers cannot collide.
        digest = hashlib.sha256(
            f"{profile.provider}:{profile.provider_user_id}".encode()
        ).hexdigest()[:24]
        return f"{profile.provider}:{digest}"

    async def create_session(self, account: OAuthAccount, *, days: int) -> str:
        """Issue a new session token; only its hash is stored."""
        raw = secrets.token_urlsafe(32)
        self._session.add(
            AuthSession(
                token_hash=hash_token(raw),
                user_id=account.user_id,
                tenant_id=account.tenant_id,
                roles=account.roles,
                expires_at=datetime.now(UTC) + timedelta(days=days),
            )
        )
        await self._session.flush()
        return raw

    async def resolve(self, raw_token: str) -> Principal | None:
        """Return the principal behind a live session token, or None when missing/expired."""
        record = (
            await self._session.execute(
                select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token))
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            return None
        return Principal(
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            roles=parse_roles(record.roles),
        )

    async def revoke(self, raw_token: str) -> None:
        await self._session.execute(
            delete(AuthSession).where(AuthSession.token_hash == hash_token(raw_token))
        )

    async def account_for(self, user_id: str, tenant_id: str) -> OAuthAccount | None:
        return (
            await self._session.execute(
                select(OAuthAccount).where(
                    OAuthAccount.user_id == user_id,
                    OAuthAccount.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
