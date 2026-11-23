from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session
from modules.conversations.repository import ConversationRepository
from modules.conversations.schemas import UsageSummary

router = APIRouter(prefix="/api/v1/usage", tags=["observability"])


@router.get("", response_model=UsageSummary)
async def get_usage_summary(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UsageSummary:
    """Return aggregated conversation counts and token usage metrics across models."""
    repo = ConversationRepository(session=session)
    return await repo.get_usage_summary()
