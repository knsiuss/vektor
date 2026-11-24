"""SQLAlchemy model for per-user, cross-session long-term memory."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from core.database import Base
from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class UserMemory(Base):
    """One persistent memory item strictly scoped to a single (tenant_id, user_id)."""

    __tablename__ = "user_memories"
    __table_args__ = (Index("ix_user_memories_owner", "tenant_id", "user_id"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
