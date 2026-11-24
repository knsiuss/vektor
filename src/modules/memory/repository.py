"""Repository for per-user long-term memories."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.models import UserMemory


class UserMemoryRepository:
    """Strictly tenant- and user-scoped CRUD for UserMemory."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_memories(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 20,
    ) -> list[UserMemory]:
        stmt = (
            select(UserMemory)
            .where(UserMemory.tenant_id == tenant_id, UserMemory.user_id == user_id)
            .order_by(UserMemory.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: str,
    ) -> UserMemory:
        cleaned = content.strip()
        row = UserMemory(tenant_id=tenant_id, user_id=user_id, content=cleaned)
        self._session.add(row)
        await self._session.flush()
        return row

    async def delete_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        memory_id: str,
    ) -> bool:
        stmt = delete(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.tenant_id == tenant_id,
            UserMemory.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))
