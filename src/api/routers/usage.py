from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.conversations.repository import ConversationRepository
from modules.conversations.schemas import UsageSummary
from modules.identity.principal import Principal
from modules.usage.budget import BudgetRepository
from modules.usage.repository import UsageEventRepository
from modules.usage.schemas import (
    BudgetStatus,
    FeedbackItem,
    ToolUsageReport,
    UsageBreakdown,
    UsageTimeseries,
)

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


@router.get("/feedback", response_model=list[FeedbackItem])
async def list_feedback(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    rating: Annotated[Literal["up", "down"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[FeedbackItem]:
    """Return the caller's recent thumbs up/down with the answers they refer to."""
    repo = UsageEventRepository(session=session, principal=principal)
    return await repo.list_feedback(rating=rating, limit=limit)


@router.get("/budget", response_model=BudgetStatus)
async def get_budget(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> BudgetStatus:
    """Return this tenant's monthly token ceiling and the tokens already spent."""
    return await BudgetRepository(session=session, principal=principal).status()


@router.get("/tools", response_model=ToolUsageReport)
async def get_tool_usage(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> ToolUsageReport:
    """Return the caller's most-used tools, their success rate and average duration."""
    repo = UsageEventRepository(session=session, principal=principal)
    return await repo.top_tools(days=days, limit=limit)
