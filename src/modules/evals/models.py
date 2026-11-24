from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


class EvalCase(Base):
    """Golden Q&A regression test case owned by a tenant."""

    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_facts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    forbidden_claims: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
