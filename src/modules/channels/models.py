from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


class ChannelConnector(Base):
    """Tenant-owned omnichannel bot connector (Telegram, WhatsApp, Discord)."""

    __tablename__ = "channel_connectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    webhook_secret: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    config: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_handover_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    knowledge_scope: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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


class ChannelSession(Base):
    """Maps an external platform user/chat ID to a Vektor conversation."""

    __tablename__ = "channel_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    connector_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("channel_connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    handover_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unknown_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )
