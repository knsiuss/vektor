from collections.abc import AsyncIterator
from typing import Annotated, cast

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.model_gateway.openai_compatible import OpenAICompatibleProvider


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a transactional AsyncSession per HTTP request."""
    session_factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.session_factory,
    )
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatService:
    """Build a ChatService wired to the configured LLM provider and repository."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))

    provider = OpenAICompatibleProvider(
        provider_name=settings.llm_provider_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        default_model=settings.llm_default_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
    )
    repository = ConversationRepository(session=session)
    return ChatService(provider=provider, repository=repository)
