from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


class ChatWidget(Base):
    """Tenant-owned public chatbot widget configuration."""

    __tablename__ = "chat_widgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    allowed_domains: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_message: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="Halo! Ada yang bisa saya bantu?",
    )
    theme: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {"primary_color": "#2563eb", "position": "bottom-right"},
    )
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


class VisitorSession(Base):
    """Anonymous visitor session mapped to a single conversation thread."""

    __tablename__ = "widget_visitor_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    widget_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_widgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    visitor_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
