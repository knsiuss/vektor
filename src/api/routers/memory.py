"""API endpoints for per-user long-term memory."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.identity.principal import Principal
from modules.memory.repository import UserMemoryRepository

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


class MemoryIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)


class MemoryOut(BaseModel):
    id: str
    content: str
    created_at: datetime


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[MemoryOut]:
    repo = UserMemoryRepository(session)
    rows = await repo.list_memories(tenant_id=principal.tenant_id, user_id=principal.user_id)
    return [MemoryOut(id=r.id, content=r.content, created_at=r.created_at) for r in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryIn,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryOut:
    repo = UserMemoryRepository(session)
    row = await repo.add_memory(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        content=payload.content,
    )
    await session.commit()
    return MemoryOut(id=row.id, content=row.content, created_at=row.created_at)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    repo = UserMemoryRepository(session)
    deleted = await repo.delete_memory(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        memory_id=memory_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    await session.commit()
