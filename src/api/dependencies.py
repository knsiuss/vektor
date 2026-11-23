from collections.abc import AsyncIterator
from typing import Annotated, cast

import httpx
from fastapi import Depends, Request
from modules.ai_runtime.retriever import KnowledgeRetriever
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.knowledge.extractors import DocumentExtractor
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.embeddings import (
    EmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
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


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    """Build the configured EmbeddingProvider for vector indexing and search."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))
    return OpenAICompatibleEmbeddingProvider(
        provider_name=settings.llm_provider_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        embedding_model=settings.llm_embedding_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
    )


def get_document_extractor(request: Request) -> DocumentExtractor:
    """Build a DocumentExtractor wired to the configured multimodal vision model."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))
    return DocumentExtractor(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        vision_model=settings.llm_vision_model or settings.llm_default_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
    )


def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> ChatService:
    """Build a ChatService wired to the LLM provider, conversation repo, and RAG retriever."""
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
    knowledge_repo = KnowledgeRepository(session=session, embedding_provider=embeddings)
    retriever = KnowledgeRetriever(knowledge_repo=knowledge_repo, llm_provider=provider)
    return ChatService(provider=provider, repository=repository, retriever=retriever)
