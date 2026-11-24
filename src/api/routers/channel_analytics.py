from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.channels.models import ChannelConnector, ChannelSession
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


class ChannelTypeMetrics(BaseModel):
    channel_type: str
    total_connectors: int
    total_sessions: int
    active_handovers: int
    ai_deflection_rate: float


class ChannelAnalyticsOut(BaseModel):
    total_connectors: int
    total_sessions: int
    active_handovers: int
    ai_deflection_rate: float
    by_channel: list[ChannelTypeMetrics]


def compute_deflection_rate(total_sessions: int, active_handovers: int) -> float:
    """Percentage of sessions handled by AI without human handover (0.0 - 1.0)."""
    if total_sessions <= 0:
        return 1.0
    handled_by_ai = max(0, total_sessions - active_handovers)
    return round(handled_by_ai / total_sessions, 4)


@router.get("/analytics", response_model=ChannelAnalyticsOut)
async def get_channel_analytics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ChannelAnalyticsOut:
    """Aggregate connector and session counts directly in SQL using GROUP BY."""
    conn_stmt = (
        select(ChannelConnector.channel_type, func.count(ChannelConnector.id))
        .where(ChannelConnector.tenant_id == principal.tenant_id)
        .group_by(ChannelConnector.channel_type)
    )
    conn_rows = (await session.execute(conn_stmt)).all()

    sess_stmt = (
        select(
            ChannelConnector.channel_type,
            func.count(ChannelSession.id),
            func.coalesce(
                func.sum(case((ChannelSession.handover_mode.is_(True), 1), else_=0)),
                0,
            ),
        )
        .join(ChannelConnector, ChannelSession.connector_id == ChannelConnector.id)
        .where(ChannelSession.tenant_id == principal.tenant_id)
        .group_by(ChannelConnector.channel_type)
    )
    sess_rows = (await session.execute(sess_stmt)).all()

    grouped: dict[str, dict[str, int]] = {}
    for ctype, count in conn_rows:
        grouped[str(ctype)] = {"connectors": int(count), "sessions": 0, "handovers": 0}
    for ctype, total_s, handovers in sess_rows:
        bucket = grouped.setdefault(
            str(ctype), {"connectors": 0, "sessions": 0, "handovers": 0}
        )
        bucket["sessions"] = int(total_s)
        bucket["handovers"] = int(handovers)

    by_channel = [
        ChannelTypeMetrics(
            channel_type=ctype,
            total_connectors=counts["connectors"],
            total_sessions=counts["sessions"],
            active_handovers=counts["handovers"],
            ai_deflection_rate=compute_deflection_rate(counts["sessions"], counts["handovers"]),
        )
        for ctype, counts in sorted(grouped.items())
    ]

    total_connectors = sum(c.total_connectors for c in by_channel)
    total_sessions = sum(c.total_sessions for c in by_channel)
    active_handovers = sum(c.active_handovers for c in by_channel)
    return ChannelAnalyticsOut(
        total_connectors=total_connectors,
        total_sessions=total_sessions,
        active_handovers=active_handovers,
        ai_deflection_rate=compute_deflection_rate(total_sessions, active_handovers),
        by_channel=by_channel,
    )
