from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


class PlatformKey(Base):
    """Platform-managed API key pool for managed billing mode."""

    __tablename__ = "platform_keys"
    __table_args__ = (Index("ix_platform_keys_provider_status", "provider", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="primary")
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    wrapped_dek: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    monthly_limit_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )


class CreditLedgerEntry(Base):
    """Immutable double-entry credit ledger row (balance = SUM(amount_micros))."""

    __tablename__ = "credit_ledger"
    __table_args__ = (Index("ix_credit_ledger_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )


class CreditReservation(Base):
    """Temporary atomic credit hold with expiration to prevent negative balances."""

    __tablename__ = "credit_reservations"
    __table_args__ = (
        Index("ix_credit_reservations_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    hold_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
