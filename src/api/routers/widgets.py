from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.identity.principal import Principal
from modules.widgets.models import ChatWidget
from modules.widgets.repository import WidgetNotFoundError, WidgetRepository
from modules.widgets.schemas import WidgetCreate, WidgetResponse, WidgetUpdate

router = APIRouter(prefix="/api/v1/widgets", tags=["widgets"])


def _to_response(widget: ChatWidget) -> WidgetResponse:
    return WidgetResponse(
        id=widget.id,
        tenant_id=widget.tenant_id,
        public_key=widget.public_key,
        name=widget.name,
        allowed_domains=widget.allowed_domains,
        system_prompt=widget.system_prompt,
        welcome_message=widget.welcome_message,
        theme=widget.theme,
        knowledge_scope=widget.knowledge_scope,
        is_active=widget.is_active,
        created_at=widget.created_at,
        updated_at=widget.updated_at,
    )


@router.post("", response_model=WidgetResponse, status_code=status.HTTP_201_CREATED)
async def create_widget(
    payload: WidgetCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> WidgetResponse:
    widget = await WidgetRepository(session).create(principal.tenant_id, payload)
    return _to_response(widget)


@router.get("", response_model=list[WidgetResponse])
async def list_widgets(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[WidgetResponse]:
    widgets = await WidgetRepository(session).list_for_tenant(principal.tenant_id)
    return [_to_response(w) for w in widgets]


@router.patch("/{widget_id}", response_model=WidgetResponse)
async def update_widget(
    widget_id: str,
    payload: WidgetUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> WidgetResponse:
    try:
        widget = await WidgetRepository(session).update(widget_id, principal.tenant_id, payload)
    except WidgetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(widget)


@router.delete("/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget(
    widget_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    try:
        await WidgetRepository(session).delete(widget_id, principal.tenant_id)
    except WidgetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
