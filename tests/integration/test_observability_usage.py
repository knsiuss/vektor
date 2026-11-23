from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.model_gateway.schemas import ModelRequest, ModelResponse, StreamChunk, TokenUsage


class _MeteredProvider:
    @property
    def provider_name(self) -> str:
        return "openrouter"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        model = request.model or "default-model"
        return ModelResponse(
            content="Tracked response.",
            provider=self.provider_name,
            model=model,
            usage=TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40),
            finish_reason="stop",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(
            delta="Tracked response.",
            model=request.model or "default-model",
            usage=TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40),
            finish_reason="stop",
        )


@asynccontextmanager
async def _test_client() -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)

    def _override_chat(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ChatService:
        return ChatService(
            provider=_MeteredProvider(),
            repository=ConversationRepository(session=session),
        )

    app.dependency_overrides[get_chat_service] = _override_chat

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def test_request_id_middleware_propagates_and_sanitizes_headers() -> None:
    """Verify valid X-Request-ID is echoed and unsafe headers are replaced."""
    async with _test_client() as client:
        valid = await client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
        unsafe = await client.get("/health", headers={"X-Request-ID": "bad\nlog-injection"})

    assert valid.headers["X-Request-ID"] == "trace-abc-123"
    assert float(valid.headers["X-Process-Time-Ms"]) >= 0.0
    assert unsafe.headers["X-Request-ID"] != "bad\nlog-injection"
    assert len(unsafe.headers["X-Request-ID"]) == 36


async def test_usage_endpoint_aggregates_tokens_by_model() -> None:
    """Verify GET /api/v1/usage accurately sums conversations, messages, and tokens."""
    async with _test_client() as client:
        await client.post("/api/v1/chat", json={"message": "Turn 1", "model": "model-a"})
        await client.post("/api/v1/chat", json={"message": "Turn 2", "model": "model-b"})

        usage_res = await client.get("/api/v1/usage")

    assert usage_res.status_code == 200
    data = usage_res.json()
    assert data["total_conversations"] == 2
    assert data["total_messages"] == 4
    assert data["prompt_tokens"] == 60
    assert data["completion_tokens"] == 20
    assert data["total_tokens"] == 80
    assert {item["model"] for item in data["by_model"]} == {"model-a", "model-b"}
