from collections.abc import AsyncIterator, Callable
from typing import Annotated, cast

import httpx
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.compaction import ConversationCompactor
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import Principal
from modules.settings.repository import ProviderSettingRepository
from modules.knowledge.extractors import DocumentExtractor
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.embeddings import (
    EmbeddingProvider,
    LocalBGEEmbeddingProvider,
    LocalHashEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    VoyageEmbeddingProvider,
)
from modules.model_gateway.openai_compatible import OpenAICompatibleProvider
from modules.tools.builtins import build_default_tool_registry
from modules.usage.metered import MeteredProvider
from modules.usage.models import KIND_CHAT, KIND_EMBEDDING, KIND_REWRITE, KIND_VISION
from modules.usage.recorder import UsageRecorder
from modules.usage.repository import UsageEventRepository


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


def get_settings(request: Request) -> Settings:
    """Return the settings bound to the running application."""
    return cast(Settings, request.app.state.settings)


def get_principal(request: Request) -> Principal:
    """Return the authenticated Principal attached by the auth middleware."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return principal


def require_admin(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    """Allow only tenant administrators."""
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )
    return principal


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Expose the application-bound async session factory for tool execution."""
    return cast(
        async_sessionmaker[AsyncSession],
        request.app.state.session_factory,
    )


def get_usage_recorder(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> UsageRecorder:
    """Return the per-request usage recorder, creating it on first use."""
    recorder = getattr(request.state, "usage_recorder", None)
    if not isinstance(recorder, UsageRecorder):
        recorder = UsageRecorder(get_session_factory(request), principal)
        request.state.usage_recorder = recorder
    return recorder


def get_embedding_provider(
    request: Request,
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
) -> EmbeddingProvider:
    """Build the configured EmbeddingProvider for vector indexing and search."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))
    model_lower = settings.llm_embedding_model.strip().lower()
    backend = settings.llm_embedding_backend
    embedding_provider_name = settings.resolved_embedding_provider_name
    usage_hook = recorder.hook(kind=KIND_EMBEDDING, provider=embedding_provider_name)

    if backend == "local-hash" or (
        backend == "auto" and model_lower in ("local", "local-hash", "local-hash-v1")
    ):
        return LocalHashEmbeddingProvider()

    if backend == "local-bge":
        return LocalBGEEmbeddingProvider(embedding_model=settings.llm_embedding_model)

    if backend == "ollama" or (backend == "auto" and embedding_provider_name.lower() == "ollama"):
        ollama_url = (
            settings.llm_embedding_base_url.strip()
            if settings.llm_embedding_base_url and settings.llm_embedding_base_url.strip()
            else "http://localhost:11434"
        )
        return OllamaEmbeddingProvider(
            base_url=ollama_url,
            embedding_model=settings.llm_embedding_model,
            timeout_seconds=max(settings.llm_timeout_seconds, 60.0),
            client=http_client,
            on_usage=usage_hook,
        )

    if backend == "voyage" or (backend == "auto" and embedding_provider_name.lower() == "voyage"):
        voyage_url = (
            settings.llm_embedding_base_url.strip()
            if settings.llm_embedding_base_url and settings.llm_embedding_base_url.strip()
            else "https://api.voyageai.com/v1"
        )
        return VoyageEmbeddingProvider(
            provider_name=embedding_provider_name,
            api_key=settings.resolved_embedding_api_key,
            base_url=voyage_url,
            embedding_model=settings.llm_embedding_model,
            timeout_seconds=settings.llm_timeout_seconds,
            client=http_client,
            on_usage=usage_hook,
        )

    return OpenAICompatibleEmbeddingProvider(
        provider_name=embedding_provider_name,
        api_key=settings.resolved_embedding_api_key,
        base_url=settings.resolved_embedding_base_url,
        embedding_model=settings.llm_embedding_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
        on_usage=usage_hook,
    )


def get_document_extractor(
    request: Request,
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
) -> DocumentExtractor:
    """Build a DocumentExtractor wired to the configured multimodal vision model."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))
    return DocumentExtractor(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        vision_model=settings.llm_vision_model or settings.llm_default_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
        on_usage=recorder.hook(kind=KIND_VISION, provider=settings.llm_provider_name),
    )


async def get_selected_model(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> str | None:
    """Return the model this user picked in settings, so the picker actually takes effect."""
    record = await ProviderSettingRepository(session=session).get(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    return record.model if record and record.model else None


def _build_chat_service(
    *,
    settings: Settings,
    http_client: httpx.AsyncClient | None,
    session: AsyncSession,
    embeddings: EmbeddingProvider,
    principal: Principal,
    recorder: UsageRecorder,
    selected_model: str | None = None,
) -> ChatService:
    base_provider = OpenAICompatibleProvider(
        provider_name=settings.llm_provider_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        default_model=selected_model or settings.llm_default_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
    )
    chat_provider = MeteredProvider(base_provider, recorder, kind=KIND_CHAT)
    rewrite_provider = MeteredProvider(base_provider, recorder, kind=KIND_REWRITE)
    repository = ConversationRepository(session=session, principal=principal)
    knowledge_repo = KnowledgeRepository(
        session=session,
        embedding_provider=embeddings,
        principal=principal,
    )
    from modules.ai_runtime.retriever import KnowledgeRetriever

    retriever = KnowledgeRetriever(knowledge_repo=knowledge_repo, llm_provider=rewrite_provider)
    tool_registry = build_default_tool_registry(
        conversation_repo=repository,
        knowledge_repo=knowledge_repo,
        session=session,
    )
    usage_repo = UsageEventRepository(session=session, principal=principal)
    return ChatService(
        provider=chat_provider,
        repository=repository,
        retriever=retriever,
        tool_registry=tool_registry,
        usage_repo=usage_repo,
        max_history_messages=settings.agent_max_history_messages,
        max_history_tokens=settings.agent_max_history_tokens,
        max_tool_iterations=settings.agent_max_tool_iterations,
        temperature=settings.llm_chat_temperature,
        stale_days=settings.retrieval_stale_days,
    )


def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    principal: Annotated[Principal, Depends(get_principal)],
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
    selected_model: Annotated[str | None, Depends(get_selected_model)],
) -> ChatService:
    """Build a ChatService wired to LLM provider, RAG retriever, and tool registry."""
    return _build_chat_service(
        settings=cast(Settings, request.app.state.settings),
        http_client=cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None)),
        session=session,
        embeddings=embeddings,
        principal=principal,
        recorder=recorder,
        selected_model=selected_model,
    )


def get_conversation_compactor(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
    selected_model: Annotated[str | None, Depends(get_selected_model)],
) -> ConversationCompactor:
    """Build a compactor that summarizes history with the configured chat provider."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))
    provider = MeteredProvider(
        OpenAICompatibleProvider(
            provider_name=settings.llm_provider_name,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            default_model=selected_model or settings.llm_default_model,
            timeout_seconds=settings.llm_timeout_seconds,
            client=http_client,
        ),
        recorder,
        kind=KIND_CHAT,
    )
    return ConversationCompactor(
        provider=provider,
        repository=ConversationRepository(session=session),
    )


ChatServiceFactory = Callable[[AsyncSession], ChatService]


def get_chat_service_factory(
    request: Request,
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    principal: Annotated[Principal, Depends(get_principal)],
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
    selected_model: Annotated[str | None, Depends(get_selected_model)],
) -> ChatServiceFactory:
    """Return a factory that binds a ChatService to a caller-owned session (for streaming)."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))

    def _factory(session: AsyncSession) -> ChatService:
        return _build_chat_service(
            settings=settings,
            http_client=http_client,
            session=session,
            embeddings=embeddings,
            principal=principal,
            recorder=recorder,
            selected_model=selected_model,
        )

    return _factory
