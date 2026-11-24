from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.conversations.repository import ConversationRepository
from modules.conversations.schemas import UsageSummary
from modules.identity.principal import Principal
from modules.usage.repository import UsageEventRepository
from modules.usage.schemas import UsageBreakdown, UsageTimeseries

router = APIRouter(prefix="/api/v1/usage", tags=["observability"])


@router.get("", response_model=UsageSummary)
async def get_usage_summary(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> UsageSummary:
    """Return aggregated conversation counts and token usage metrics for the caller."""
    repo = ConversationRepository(session=session, principal=principal)
    return await repo.get_usage_summary()


@router.get("/breakdown", response_model=UsageBreakdown)
async def get_usage_breakdown(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> UsageBreakdown:
    """Return the caller's upstream model usage grouped by kind and model."""
    repo = UsageEventRepository(session=session, principal=principal)
    return await repo.breakdown(since=since, until=until)


@router.get("/timeseries", response_model=UsageTimeseries)
async def get_usage_timeseries(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    days: Annotated[int, Query(ge=1, le=365)] = 7,
) -> UsageTimeseries:
    """Return daily conversation activity for the caller over the last N days."""
    repo = UsageEventRepository(session=session, principal=principal)
    return await repo.timeseries(days=days)
