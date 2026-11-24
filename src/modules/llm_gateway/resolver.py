import json
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.billing.models import PlatformKey
from modules.llm_gateway.models import ProviderKey, TenantPolicy
from modules.llm_gateway.vault import compute_fingerprint, decrypt_api_key, encrypt_api_key


class KeyResolutionError(Exception):
    """Base error raised when a tenant credential cannot be resolved."""


class NoKeyConfiguredError(KeyResolutionError):
    """Raised when BYOK mode has no active key for the requested provider."""


class ModelNotAllowedError(KeyResolutionError):
    """Raised when the tenant policy restricts the requested model."""


@dataclass(frozen=True, slots=True)
class Credential:
    """Ephemeral decrypted credential held only in LLM Gateway memory for one call."""

    source: Literal["byok", "managed"]
    ref: str
    billable: bool
    api_key: str
    base_url: str | None = None


class KeyResolver:
    """Resolves BYOK vault keys or Managed platform pool keys per tenant policy."""

    def __init__(self, session: AsyncSession, *, master_key: str) -> None:
        self._session = session
        self._master_key = master_key

    async def get_or_create_policy(self, tenant_id: str) -> TenantPolicy:
        stmt = select(TenantPolicy).where(TenantPolicy.tenant_id == tenant_id)
        policy = (await self._session.execute(stmt)).scalar_one_or_none()
        if policy is None:
            policy = TenantPolicy(tenant_id=tenant_id, key_mode="byok")
            self._session.add(policy)
            await self._session.flush()
        return policy

    async def store_byok_key(
        self,
        *,
        tenant_id: str,
        provider: str,
        label: str,
        plaintext_key: str,
        base_url: str | None = None,
    ) -> ProviderKey:
        fp = compute_fingerprint(plaintext_key.strip(), master_key=self._master_key)
        dup_stmt = select(ProviderKey).where(
            ProviderKey.tenant_id == tenant_id,
            ProviderKey.fingerprint == fp,
            ProviderKey.status == "active",
        )
        if (await self._session.execute(dup_stmt)).scalar_one_or_none() is not None:
            raise ValueError("This API key is already stored for this tenant.")

        key_id = str(uuid4())
        enc = encrypt_api_key(
            plaintext_key,
            master_key=self._master_key,
            tenant_id=tenant_id,
            key_id=key_id,
        )
        record = ProviderKey(
            id=key_id,
            tenant_id=tenant_id,
            provider=provider.strip().lower(),
            label=label.strip() or "Default",
            ciphertext=enc.ciphertext,
            wrapped_dek=enc.wrapped_dek,
            last4=enc.last4,
            fingerprint=enc.fingerprint,
            base_url=base_url,
            status="active",
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def mark_invalid(self, key_id: str) -> None:
        stmt = select(ProviderKey).where(ProviderKey.id == key_id)
        record = (await self._session.execute(stmt)).scalar_one_or_none()
        if record is not None:
            record.status = "invalid"
            await self._session.flush()

    async def resolve(
        self,
        *,
        tenant_id: str,
        provider: str,
        model_id: str,
    ) -> Credential:
        policy = await self.get_or_create_policy(tenant_id)
        allowed = json.loads(policy.allowed_models_json or "[]")
        if allowed and model_id not in allowed:
            raise ModelNotAllowedError(f"Model '{model_id}' is not allowed by tenant policy.")

        norm_provider = provider.strip().lower()
        if policy.key_mode == "byok":
            stmt = (
                select(ProviderKey)
                .where(
                    ProviderKey.tenant_id == tenant_id,
                    ProviderKey.provider == norm_provider,
                    ProviderKey.status == "active",
                )
                .order_by(ProviderKey.created_at.desc())
            )
            key = (await self._session.execute(stmt)).scalars().first()
            if key is not None:
                plain = decrypt_api_key(
                    key.ciphertext,
                    key.wrapped_dek,
                    master_key=self._master_key,
                    tenant_id=tenant_id,
                    key_id=key.id,
                )
                return Credential(
                    source="byok",
                    ref=key.id,
                    billable=False,
                    api_key=plain,
                    base_url=key.base_url,
                )
            if not policy.fallback_to_credits:
                raise NoKeyConfiguredError(
                    f"No active BYOK key configured for provider '{norm_provider}'."
                )

        pool_stmt = (
            select(PlatformKey)
            .where(PlatformKey.provider == norm_provider, PlatformKey.status == "active")
            .order_by(PlatformKey.created_at.asc())
        )
        pool_key = (await self._session.execute(pool_stmt)).scalars().first()
        if pool_key is None:
            raise NoKeyConfiguredError(
                f"No active platform key available for provider '{norm_provider}'."
            )
        plain = decrypt_api_key(
            pool_key.ciphertext,
            pool_key.wrapped_dek,
            master_key=self._master_key,
            tenant_id="platform",
            key_id=pool_key.id,
        )
        return Credential(source="managed", ref=pool_key.id, billable=True, api_key=plain)
