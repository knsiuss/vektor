from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.approvals.models import ActionApproval


class ApprovalNotFoundError(Exception):
    """Raised when an approval item does not exist for the tenant."""


class ApprovalStateError(Exception):
    """Raised when attempting an invalid state transition on an approval item."""


def validate_approval_transition(current: str, target: str) -> None:
    """Allow pending -> approved|rejected and approved -> executed only."""
    allowed = {
        "pending": {"approved", "rejected"},
        "approved": {"executed"},
        "rejected": set(),
        "executed": set(),
    }
    if target not in allowed.get(current, set()):
        raise ApprovalStateError(f"Cannot transition approval from {current!r} to {target!r}.")


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        conversation_id: str | None = None,
    ) -> ActionApproval:
        row = ActionApproval(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            arguments=arguments,
            status="pending",
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        status_filter: str | None = None,
    ) -> list[ActionApproval]:
        stmt = select(ActionApproval).where(ActionApproval.tenant_id == tenant_id)
        if status_filter:
            stmt = stmt.where(ActionApproval.status == status_filter)
        stmt = stmt.order_by(ActionApproval.created_at.desc()).limit(100)
        return list((await self._session.execute(stmt)).scalars().all())

    async def decide(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        decision: Literal["approved", "rejected"],
        decided_by: str,
    ) -> ActionApproval:
        stmt = select(ActionApproval).where(
            ActionApproval.id == approval_id,
            ActionApproval.tenant_id == tenant_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ApprovalNotFoundError("Approval request not found.")
        validate_approval_transition(row.status, decision)
        row.status = decision
        row.decided_by = decided_by
        row.decided_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get_for_tenant(self, approval_id: str, tenant_id: str) -> ActionApproval:
        stmt = select(ActionApproval).where(
            ActionApproval.id == approval_id,
            ActionApproval.tenant_id == tenant_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ApprovalNotFoundError("Approval request not found.")
        return row

    async def mark_executed(self, row: ActionApproval) -> ActionApproval:
        validate_approval_transition(row.status, "executed")
        row.status = "executed"
        await self._session.flush()
        await self._session.refresh(row)
        return row
