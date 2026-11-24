from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.channels.event_bus import inbox_event_bus
from modules.channels.repository import ChannelNotFoundError, ChannelRepository
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


class AssignAgentIn(BaseModel):
    agent_id: str | None = None


class AssignAgentOut(BaseModel):
    session_id: str
    assigned_agent_id: str | None


@router.get("/stream")
async def stream_inbox_events(
    principal: Annotated[Principal, Depends(get_principal)],
) -> StreamingResponse:
    """Real-time SSE stream of incoming channel messages and handover updates."""

    async def _gen() -> AsyncIterator[str]:
        yield "event: inbox.connected\ndata: {}\n\n"
        async for frame in inbox_event_bus.subscribe(principal.tenant_id):
            yield frame

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@router.patch("/sessions/{session_id}/assign", response_model=AssignAgentOut)
async def assign_inbox_session(
    session_id: str,
    payload: AssignAgentIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AssignAgentOut:
    """Assign (or unassign) a channel session to a human agent."""
    target_agent = payload.agent_id if payload.agent_id is not None else principal.user_id
    try:
        row = await ChannelRepository(session).assign_agent(
            session_id, principal.tenant_id, target_agent
        )
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await inbox_event_bus.publish(
        principal.tenant_id,
        "inbox.assigned",
        {"session_id": row.id, "assigned_agent_id": row.assigned_agent_id},
    )
    return AssignAgentOut(session_id=row.id, assigned_agent_id=row.assigned_agent_id)
