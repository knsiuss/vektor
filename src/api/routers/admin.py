from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal, require_admin
from modules.conversations.repository import ConversationRepository
from modules.conversations.schemas import AdminConversationSummary, UsageSummary
from modules.identity.principal import Principal
from modules.identity.repository import AuditRepository
from modules.identity.schemas import AuditLogItem
from modules.usage.budget import BudgetRepository
from modules.usage.repository import UsageEventRepository
from modules.usage.schemas import BudgetStatus, BudgetUpdateIn, UsageBreakdown

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _repo(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ConversationRepository:
    return ConversationRepository(session=session, principal=principal)


@router.get("/conversations", response_model=list[AdminConversationSummary])
async def list_tenant_conversations(
    repo: Annotated[ConversationRepository, Depends(_repo)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AdminConversationSummary]:
    """List all conversations in the admin's tenant (access is audited)."""
    items = await repo.list_tenant_conversations(limit=limit, offset=offset)
    return [AdminConversationSummary.model_validate(item) for item in items]


@router.get("/usage", response_model=UsageSummary)
async def get_tenant_usage(
    repo: Annotated[ConversationRepository, Depends(_repo)],
) -> UsageSummary:
    """Return conversation and token usage aggregated over the whole tenant."""
    return await repo.get_usage_summary(tenant_wide=True)


@router.get("/usage/breakdown", response_model=UsageBreakdown)
async def get_tenant_usage_breakdown(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    by_user: Annotated[bool, Query()] = True,
) -> UsageBreakdown:
    """Upstream model usage for the whole tenant, split per user unless by_user=false."""
    repo = UsageEventRepository(session=session, principal=principal)
    return await repo.breakdown(tenant_wide=True, by_user=by_user, since=since, until=until)


@router.get("/audit-log", response_model=list[AuditLogItem])
async def get_audit_log(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogItem]:
    """Return privileged-access audit records for the admin's tenant, newest first."""
    rows = await AuditRepository(session).list_for_tenant(
        principal.tenant_id, limit=limit, offset=offset
    )
    return [AuditLogItem.model_validate(row) for row in rows]


@router.put("/budget", response_model=BudgetStatus)
async def set_tenant_budget(
    payload: BudgetUpdateIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> BudgetStatus:
    """Set the tenant's monthly token ceiling used to reject exhausted requests."""
    return await BudgetRepository(session=session, principal=principal).set_limit(
        monthly_token_limit=payload.monthly_token_limit,
        warn_ratio=payload.warn_ratio,
    )
