from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.billing.models import CreditLedgerEntry, CreditReservation


class InsufficientCreditsError(Exception):
    """Raised when a tenant's available credit balance is below the required hold."""


class CreditLedgerService:
    """Double-entry credit ledger with atomic reserve/settle/release holds."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_balance_micros(self, tenant_id: str) -> int:
        stmt = select(func.coalesce(func.sum(CreditLedgerEntry.amount_micros), 0)).where(
            CreditLedgerEntry.tenant_id == tenant_id
        )
        total = (await self._session.execute(stmt)).scalar_one()
        return int(total)

    async def grant_credits(
        self,
        *,
        tenant_id: str,
        amount_micros: int,
        ref_id: str,
    ) -> CreditLedgerEntry:
        if amount_micros <= 0:
            raise ValueError("Credit grant amount must be positive.")
        entry = CreditLedgerEntry(
            tenant_id=tenant_id,
            entry_type="topup",
            amount_micros=amount_micros,
            ref_id=ref_id,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def reserve(
        self,
        *,
        tenant_id: str,
        hold_micros: int,
        ttl_seconds: int = 120,
    ) -> CreditReservation:
        if hold_micros <= 0:
            raise ValueError("Hold amount must be positive.")
        balance = await self.get_balance_micros(tenant_id)
        if balance < hold_micros:
            raise InsufficientCreditsError(
                f"Insufficient credits: balance={balance}, required_hold={hold_micros}."
            )

        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        reservation = CreditReservation(
            tenant_id=tenant_id,
            hold_micros=hold_micros,
            status="open",
            expires_at=expires_at,
        )
        self._session.add(reservation)
        await self._session.flush()

        self._session.add(
            CreditLedgerEntry(
                tenant_id=tenant_id,
                entry_type="reserve",
                amount_micros=-hold_micros,
                ref_id=reservation.id,
            )
        )
        await self._session.flush()
        return reservation

    async def settle(
        self,
        reservation_id: str,
        *,
        actual_cost_micros: int,
        markup_pct: float = 0.0,
    ) -> int:
        res = await self._get_open_reservation(reservation_id)
        charge = round(max(0, actual_cost_micros) * (1.0 + max(0.0, markup_pct)))
        refund = res.hold_micros - charge
        res.status = "settled"
        if refund != 0:
            self._session.add(
                CreditLedgerEntry(
                    tenant_id=res.tenant_id,
                    entry_type="settle",
                    amount_micros=refund,
                    ref_id=res.id,
                )
            )
        await self._session.flush()
        return charge

    async def release(self, reservation_id: str) -> None:
        res = await self._get_open_reservation(reservation_id)
        res.status = "released"
        self._session.add(
            CreditLedgerEntry(
                tenant_id=res.tenant_id,
                entry_type="release",
                amount_micros=res.hold_micros,
                ref_id=res.id,
            )
        )
        await self._session.flush()

    async def expire_stale_reservations(self, *, now: datetime | None = None) -> int:
        cutoff = now or datetime.now(UTC)
        stmt = select(CreditReservation).where(
            CreditReservation.status == "open",
            CreditReservation.expires_at <= cutoff,
        )
        stale = (await self._session.execute(stmt)).scalars().all()
        for res in stale:
            res.status = "released"
            self._session.add(
                CreditLedgerEntry(
                    tenant_id=res.tenant_id,
                    entry_type="release",
                    amount_micros=res.hold_micros,
                    ref_id=res.id,
                )
            )
        await self._session.flush()
        return len(stale)

    async def _get_open_reservation(self, reservation_id: str) -> CreditReservation:
        stmt = select(CreditReservation).where(CreditReservation.id == reservation_id)
        res = (await self._session.execute(stmt)).scalar_one_or_none()
        if res is None or res.status != "open":
            raise ValueError(f"Reservation '{reservation_id}' is missing or not open.")
        return res
