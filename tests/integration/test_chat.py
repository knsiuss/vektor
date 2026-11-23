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
from modules.model_gateway.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from modules.model_gateway.schemas import ModelRequest, ModelResponse, TokenUsage


class _FakeProvider:
    def __init__(
        self,
        *,
        reply: str = "Hello from Vektor!",
        error: Exception | None = None,
    ) -> None:
        self._reply = reply
        self._error = error
        self.requests: list[ModelRequest] = []

    @property
    def provider_name(self) -> str:
        return "fake-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return ModelResponse(
            content=self._reply,
            provider=self.provider_name,
            model=request.model or "fake-model-v1",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
            finish_reason="stop",
        )


@asynccontextmanager
async def _test_client(provider: _FakeProvider) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)

    def _override_chat_service(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ChatService:
        return ChatService(
            provider=provider,
            repository=ConversationRepository(session=session),
        )

    app.dependency_overrides[get_chat_service] = _override_chat_service

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def test_chat_endpoint_creates_conversation_and_persists_multi_turn_history() -> None:
    """Verify multi-turn conversations persist messages and replay history to the LLM."""
    fake_provider = _FakeProvider(reply="First response.")

    async with _test_client(fake_provider) as client:
        first = await client.post("/api/v1/chat", json={"message": "My name is Quincy."})
        assert first.status_code == 200
        first_body = first.json()
        conversation_id = first_body["conversation_id"]
        assert conversation_id
        assert first_body["reply"] == "First response."

        fake_provider._reply = "Your name is Quincy."
        second = await client.post(
            "/api/v1/chat",
            json={"conversation_id": conversation_id, "message": "What is my name?"},
        )

    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    assert len(fake_provider.requests) == 2

    second_messages = fake_provider.requests[1].messages
    assert [m.role for m in second_messages] == ["system", "user", "assistant", "user"]
    assert second_messages[1].content == "My name is Quincy."
    assert second_messages[2].content == "First response."
    assert second_messages[3].content == "What is my name?"


async def test_chat_endpoint_returns_404_for_unknown_conversation_id() -> None:
    """Verify referencing a nonexistent conversation ID returns HTTP 404."""
    async with _test_client(_FakeProvider()) as client:
        response = await client.post(
            "/api/v1/chat",
            json={"conversation_id": "nonexistent-id", "message": "Hello?"},
        )

    assert response.status_code == 404


async def test_chat_endpoint_rejects_empty_message() -> None:
    """Verify empty user messages fail validation with HTTP 422."""
    async with _test_client(_FakeProvider()) as client:
        response = await client.post("/api/v1/chat", json={"message": ""})

    assert response.status_code == 422


async def test_chat_endpoint_maps_auth_error_to_503() -> None:
    """Verify missing/invalid provider credentials return 503 without leaking secrets."""
    provider = _FakeProvider(
        error=ProviderAuthenticationError("Invalid key", provider="fake-provider")
    )
    async with _test_client(provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "Hi"})

    assert response.status_code == 503


async def test_chat_endpoint_maps_rate_limit_to_429() -> None:
    """Verify upstream rate limits return HTTP 429."""
    provider = _FakeProvider(error=ProviderRateLimitError("Rate limited", provider="fake-provider"))
    async with _test_client(provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "Hi"})

    assert response.status_code == 429


async def test_chat_endpoint_maps_timeout_to_504() -> None:
    """Verify upstream timeouts return HTTP 504."""
    provider = _FakeProvider(error=ProviderTimeoutError("Timed out", provider="fake-provider"))
    async with _test_client(provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "Hi"})

    assert response.status_code == 504
