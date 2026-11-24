from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.approvals.executor import ActionExecutionError, ActionExecutorRegistry
from modules.approvals.models import ActionApproval
from modules.approvals.repository import (
    ApprovalNotFoundError,
    ApprovalRepository,
    ApprovalStateError,
)
from modules.identity.principal import Principal
from modules.llm_gateway.ssrf import SSRFBlockedError, validate_custom_base_url

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])
_executor_registry = ActionExecutorRegistry()


class ApprovalCreateIn(BaseModel):
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None


class ApprovalDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]


class ApprovalOut(BaseModel):
    id: str
    conversation_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    status: str
    decided_by: str | None
    created_at: datetime
    decided_at: datetime | None


def _to_out(row: ActionApproval) -> ApprovalOut:
    return ApprovalOut(
        id=row.id,
        conversation_id=row.conversation_id,
        tool_name=row.tool_name,
        arguments=row.arguments,
        status=row.status,
        decided_by=row.decided_by,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    status_filter: str | None = Query(None, alias="status"),
) -> list[ApprovalOut]:
    rows = await ApprovalRepository(session).list_for_tenant(
        principal.tenant_id, status_filter=status_filter
    )
    return [_to_out(r) for r in rows]


@router.post("", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED)
async def create_approval(
    payload: ApprovalCreateIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ApprovalOut:
    row = await ApprovalRepository(session).create(
        tenant_id=principal.tenant_id,
        tool_name=payload.tool_name,
        arguments=payload.arguments,
        conversation_id=payload.conversation_id,
    )
    return _to_out(row)


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecisionIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ApprovalOut:
    """Approve or reject a pending write-action draft."""
    try:
        row = await ApprovalRepository(session).decide(
            approval_id,
            tenant_id=principal.tenant_id,
            decision=payload.decision,
            decided_by=principal.user_id,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_out(row)


@router.post("/{approval_id}/execute", response_model=ApprovalOut)
async def execute_approval(
    approval_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ApprovalOut:
    """Execute a previously approved write-action safely (SSRF-checked for webhooks)."""
    repo = ApprovalRepository(session)
    try:
        row = await repo.get_for_tenant(approval_id, principal.tenant_id)
        if row.tool_name == "http_webhook":
            url = str(row.arguments.get("url", ""))
            safe_url = validate_custom_base_url(url, allow_local=False)
            http_client = request.app.state.http_client
            await http_client.post(safe_url, json=row.arguments.get("body", {}), timeout=15.0)
        else:
            await _executor_registry.execute(row)
        row = await repo.mark_executed(row)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ApprovalStateError, ActionExecutionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SSRFBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_out(row)
