"""Tenant-wide monthly token budget: read the current state and enforce it."""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.identity.principal import Principal
from modules.usage.models import TenantBudget, UsageEvent
from modules.usage.schemas import BudgetStatus


class BudgetExceededError(Exception):
    """Raised when the tenant has used up its monthly token budget."""

    def __init__(self, status: BudgetStatus) -> None:
        super().__init__(
            f"Monthly token budget exhausted for {status.month} "
            f"({status.used_tokens:,} of {status.limit_tokens:,} tokens)."
        )
        self.status = status


def month_start(moment: datetime | None = None) -> datetime:
    """First instant of the current UTC month."""
    now = moment or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class BudgetRepository:
    """Reads and updates the monthly token ceiling for one tenant."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal

    async def _budget(self) -> TenantBudget | None:
        return (
            await self._session.execute(
                select(TenantBudget).where(TenantBudget.tenant_id == self._principal.tenant_id)
            )
        ).scalar_one_or_none()

    async def used_tokens(self, since: datetime) -> int:
        """Tokens this tenant spent since the given instant, across all users."""
        stmt = select(func.coalesce(func.sum(UsageEvent.total_tokens), 0)).where(
            UsageEvent.tenant_id == self._principal.tenant_id,
            UsageEvent.created_at >= since,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def status(self) -> BudgetStatus:
        """Current month's spend against the ceiling, if one is configured."""
        start = month_start()
        used = await self.used_tokens(start)
        budget = await self._budget()
        if budget is None:
            return BudgetStatus(
                month=start.date().isoformat(),
                limit_tokens=None,
                used_tokens=used,
                ratio=0.0,
                state="unlimited",
            )

        limit = budget.monthly_token_limit
        ratio = round(used / limit, 4) if limit else 1.0
        state: Literal["ok", "warning", "exhausted"]
        if used >= limit:
            state = "exhausted"
        elif ratio >= budget.warn_ratio:
            state = "warning"
        else:
            state = "ok"
        return BudgetStatus(
            month=start.date().isoformat(),
            limit_tokens=limit,
            used_tokens=used,
            ratio=ratio,
            state=state,
        )

    async def ensure_within_budget(self) -> BudgetStatus:
        """Return the status, raising when the tenant has spent its whole budget."""
        status = await self.status()
        if status.state == "exhausted":
            raise BudgetExceededError(status)
        return status

    async def set_limit(self, *, monthly_token_limit: int, warn_ratio: float) -> BudgetStatus:
        """Create or replace the tenant's ceiling."""
        budget = await self._budget()
        if budget is None:
            budget = TenantBudget(
                tenant_id=self._principal.tenant_id,
                monthly_token_limit=monthly_token_limit,
                warn_ratio=warn_ratio,
            )
            self._session.add(budget)
        else:
            budget.monthly_token_limit = monthly_token_limit
            budget.warn_ratio = warn_ratio
        await self._session.flush()
        return await self.status()
