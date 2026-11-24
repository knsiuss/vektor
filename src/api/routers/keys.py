"""Tenant BYOK key vault, policy, and managed credit endpoints."""

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal, get_settings
from api.security import SlidingWindowRateLimiter
from core.config.settings import Settings
from modules.billing.ledger import CreditLedgerService
from modules.identity.principal import Principal
from modules.llm_gateway.models import ProviderKey
from modules.llm_gateway.resolver import KeyResolver
from modules.llm_gateway.ssrf import SSRFBlockedError, validate_custom_base_url

router = APIRouter(prefix="/api/v1", tags=["gateway-vault"])
_KEY_WRITE_LIMITER = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)


def _master_key(settings: Settings) -> str:
    if settings.kms_master_key is not None and settings.kms_master_key.get_secret_value().strip():
        return settings.kms_master_key.get_secret_value().strip()
    if settings.llm_api_key is not None and settings.llm_api_key.get_secret_value().strip():
        return settings.llm_api_key.get_secret_value().strip()
    return "vektor-dev-kms-master-key"


class KeyCreateIn(BaseModel):
    provider: str = Field(..., min_length=1, max_length=32)
    label: str = Field(default="Default", min_length=1, max_length=80)
    api_key: str = Field(..., min_length=8, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)


class KeyRotateIn(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=512)


class KeyOut(BaseModel):
    id: str
    provider: str
    label: str
    last4: str
    base_url: str | None
    status: str
    created_at: datetime


class TenantPolicyIn(BaseModel):
    key_mode: Literal["byok", "managed"] = "byok"
    allowed_models: list[str] = Field(default_factory=list)
    daily_cap_usd: float | None = Field(default=None, ge=0.0)
    fallback_to_credits: bool = False


class TenantPolicyOut(BaseModel):
    tenant_id: str
    key_mode: str
    allowed_models: list[str]
    daily_cap_usd: float | None
    fallback_to_credits: bool


class CreditGrantIn(BaseModel):
    amount_micros: int = Field(..., gt=0)
    ref_id: str = Field(default="admin-grant", min_length=1, max_length=64)


class CreditBalanceOut(BaseModel):
    tenant_id: str
    balance_micros: int
    balance_usd: float


def _to_key_out(rec: ProviderKey) -> KeyOut:
    return KeyOut(
        id=rec.id,
        provider=rec.provider,
        label=rec.label,
        last4=rec.last4,
        base_url=rec.base_url,
        status=rec.status,
        created_at=rec.created_at,
    )


@router.get("/keys", response_model=list[KeyOut])
async def list_vault_keys(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[KeyOut]:
    stmt = (
        select(ProviderKey)
        .where(ProviderKey.tenant_id == principal.tenant_id)
        .order_by(ProviderKey.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_key_out(r) for r in rows]


@router.post("/keys", response_model=KeyOut, status_code=status.HTTP_201_CREATED)
async def create_vault_key(
    payload: KeyCreateIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> KeyOut:
    decision = _KEY_WRITE_LIMITER.check(f"keys:{principal.tenant_id}:{principal.user_id}")
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many key registration attempts.",
        )

    safe_url: str | None = None
    if payload.base_url and payload.base_url.strip():
        try:
            safe_url = validate_custom_base_url(
                payload.base_url,
                allow_local=settings.gateway_allow_local_endpoints,
            )
        except SSRFBlockedError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    resolver = KeyResolver(session, master_key=_master_key(settings))
    try:
        record = await resolver.store_byok_key(
            tenant_id=principal.tenant_id,
            provider=payload.provider,
            label=payload.label,
            plaintext_key=payload.api_key,
            base_url=safe_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return _to_key_out(record)


@router.post("/keys/{key_id}/rotate", response_model=KeyOut)
async def rotate_vault_key(
    key_id: str,
    payload: KeyRotateIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> KeyOut:
    stmt = select(ProviderKey).where(
        ProviderKey.id == key_id,
        ProviderKey.tenant_id == principal.tenant_id,
    )
    old_key = (await session.execute(stmt)).scalar_one_or_none()
    if old_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found.")

    old_key.status = "revoked"
    resolver = KeyResolver(session, master_key=_master_key(settings))
    try:
        new_key = await resolver.store_byok_key(
            tenant_id=principal.tenant_id,
            provider=old_key.provider,
            label=old_key.label,
            plaintext_key=payload.api_key,
            base_url=old_key.base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return _to_key_out(new_key)


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vault_key(
    key_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    stmt = select(ProviderKey).where(
        ProviderKey.id == key_id,
        ProviderKey.tenant_id == principal.tenant_id,
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found.")
    await session.delete(record)
    await session.commit()


@router.get("/tenant/policy", response_model=TenantPolicyOut)
async def get_tenant_policy(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantPolicyOut:
    resolver = KeyResolver(session, master_key=_master_key(settings))
    policy = await resolver.get_or_create_policy(principal.tenant_id)
    await session.commit()
    return TenantPolicyOut(
        tenant_id=policy.tenant_id,
        key_mode=policy.key_mode,
        allowed_models=json.loads(policy.allowed_models_json or "[]"),
        daily_cap_usd=policy.daily_cap_usd,
        fallback_to_credits=policy.fallback_to_credits,
    )


@router.put("/tenant/policy", response_model=TenantPolicyOut)
async def update_tenant_policy(
    payload: TenantPolicyIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantPolicyOut:
    resolver = KeyResolver(session, master_key=_master_key(settings))
    policy = await resolver.get_or_create_policy(principal.tenant_id)
    policy.key_mode = payload.key_mode
    policy.allowed_models_json = json.dumps(payload.allowed_models)
    policy.daily_cap_usd = payload.daily_cap_usd
    policy.fallback_to_credits = payload.fallback_to_credits
    await session.commit()
    return TenantPolicyOut(
        tenant_id=policy.tenant_id,
        key_mode=policy.key_mode,
        allowed_models=payload.allowed_models,
        daily_cap_usd=policy.daily_cap_usd,
        fallback_to_credits=policy.fallback_to_credits,
    )


@router.get("/credits/balance", response_model=CreditBalanceOut)
async def get_credit_balance(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> CreditBalanceOut:
    ledger = CreditLedgerService(session)
    micros = await ledger.get_balance_micros(principal.tenant_id)
    return CreditBalanceOut(
        tenant_id=principal.tenant_id,
        balance_micros=micros,
        balance_usd=round(micros / 1_000_000, 4),
    )


@router.post("/credits/grant", response_model=CreditBalanceOut, status_code=status.HTTP_201_CREATED)
async def grant_tenant_credits(
    payload: CreditGrantIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> CreditBalanceOut:
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to grant credits.",
        )
    ledger = CreditLedgerService(session)
    await ledger.grant_credits(
        tenant_id=principal.tenant_id,
        amount_micros=payload.amount_micros,
        ref_id=payload.ref_id,
    )
    await session.commit()
    micros = await ledger.get_balance_micros(principal.tenant_id)
    return CreditBalanceOut(
        tenant_id=principal.tenant_id,
        balance_micros=micros,
        balance_usd=round(micros / 1_000_000, 4),
    )
