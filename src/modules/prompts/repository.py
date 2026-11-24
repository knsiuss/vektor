"""Read and write a user's Markdown prompt overrides."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.prompts.models import PromptTemplate


class PromptRepository:
    """Per-user prompt storage; scope comes from the principal."""

    def __init__(self, session: AsyncSession, *, tenant_id: str, user_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_id = user_id

    async def list_overrides(self) -> dict[str, str]:
        rows = (
            await self._session.execute(
                select(PromptTemplate).where(
                    PromptTemplate.tenant_id == self._tenant_id,
                    PromptTemplate.user_id == self._user_id,
                )
            )
        ).scalars()
        return {row.key: row.content for row in rows}

    async def get(self, key: str) -> str | None:
        row = (
            await self._session.execute(
                select(PromptTemplate).where(
                    PromptTemplate.tenant_id == self._tenant_id,
                    PromptTemplate.user_id == self._user_id,
                    PromptTemplate.key == key,
                )
            )
        ).scalar_one_or_none()
        return row.content if row else None

    async def upsert(self, key: str, content: str) -> None:
        row = (
            await self._session.execute(
                select(PromptTemplate).where(
                    PromptTemplate.tenant_id == self._tenant_id,
                    PromptTemplate.user_id == self._user_id,
                    PromptTemplate.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            self._session.add(
                PromptTemplate(
                    tenant_id=self._tenant_id,
                    user_id=self._user_id,
                    key=key,
                    content=content,
                )
            )
        else:
            row.content = content
        await self._session.flush()

    async def reset(self, key: str) -> None:
        await self._session.execute(
            delete(PromptTemplate).where(
                PromptTemplate.tenant_id == self._tenant_id,
                PromptTemplate.user_id == self._user_id,
                PromptTemplate.key == key,
            )
        )
