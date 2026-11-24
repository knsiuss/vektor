"""Per-user AI provider settings persisted in the database.

Each authenticated user can store their preferred provider (e.g. OpenAI, Anthropic,
Google Gemini, Custom), the model to use, an API key (hash only), an optional base
URL for self-hosted/custom endpoints, and the last connection check result.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


class ProviderSetting(Base):
    """One row per user: their configured AI provider and connection state."""

    __tablename__ = "provider_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)

    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    connection_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="disconnected"
    )
    connection_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
