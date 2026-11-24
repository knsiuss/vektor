from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


class TenantPolicy(Base):
    """Per-tenant LLM Gateway key mode, allowlist, and spend controls."""

    __tablename__ = "tenant_policies"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="byok")
    allowed_models_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    daily_cap_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    fallback_to_credits: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )


class ProviderKey(Base):
    """Envelope-encrypted BYOK provider key owned by a tenant."""

    __tablename__ = "provider_keys"
    __table_args__ = (
        Index("ix_provider_keys_tenant_provider", "tenant_id", "provider"),
        Index("ix_provider_keys_tenant_fp", "tenant_id", "fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="Default")
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    wrapped_dek: Mapped[str] = mapped_column(Text, nullable=False)
    last4: Mapped[str] = mapped_column(String(8), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )


class ModelRegistryEntry(Base):
    """Versioned model capabilities, support tier, and pricing per 1M tokens (micro-USD)."""

    __tablename__ = "model_registry"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[str] = mapped_column(String(24), nullable=False, default="standard")
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=128000)
    caps_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    price_in_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    price_out_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    price_cache_write_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    price_cache_read_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="verified")
    eval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    eval_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
