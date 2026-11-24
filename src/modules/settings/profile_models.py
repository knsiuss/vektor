from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


class ProviderProfile(Base):
    """Named AI provider API configuration allowing multiple APIs per user."""

    __tablename__ = "provider_profiles"
    __table_args__ = (Index("ix_provider_profiles_tenant_user", "tenant_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )
