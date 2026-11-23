import httpx

from api.dependencies import get_chat_service
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
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
        self.last_request: ModelRequest | None = None

    @property
    def provider_name(self) -> str:
        return "fake-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.last_request = request
        if self._error is not None:
            raise self._error
        return ModelResponse(
            content=self._reply,
            provider=self.provider_name,
            model=request.model or "fake-model-v1",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
            finish_reason="stop",
        )


def _test_app(provider: _FakeProvider) -> httpx.AsyncClient:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    app = create_app(settings=settings)
    app.dependency_overrides[get_chat_service] = lambda: ChatService(provider=provider)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_chat_endpoint_returns_reply_and_injects_system_prompt() -> None:
    """Verify POST /api/v1/chat loads Markdown system prompt and returns normalized response."""
    fake_provider = _FakeProvider(reply="System operational.")

    async with _test_app(fake_provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "Status check"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "System operational."
    assert body["provider"] == "fake-provider"
    assert body["model"] == "fake-model-v1"
    assert body["usage"] == {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}

    assert fake_provider.last_request is not None
    assert len(fake_provider.last_request.messages) == 2
    assert fake_provider.last_request.messages[0].role == "system"
    assert "You are Vektor" in fake_provider.last_request.messages[0].content
    assert fake_provider.last_request.messages[1].role == "user"
    assert fake_provider.last_request.messages[1].content == "Status check"


async def test_chat_endpoint_rejects_empty_message() -> None:
    """Verify empty user messages fail validation with HTTP 422."""
    async with _test_app(_FakeProvider()) as client:
        response = await client.post("/api/v1/chat", json={"message": ""})

    assert response.status_code == 422


async def test_chat_endpoint_maps_auth_error_to_503() -> None:
    """Verify missing/invalid provider credentials return 503 without leaking secrets."""
    provider = _FakeProvider(
        error=ProviderAuthenticationError("Invalid key", provider="fake-provider")
    )
    async with _test_app(provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "Hi"})

    assert response.status_code == 503


async def test_chat_endpoint_maps_rate_limit_to_429() -> None:
    """Verify upstream rate limits return HTTP 429."""
    provider = _FakeProvider(error=ProviderRateLimitError("Rate limited", provider="fake-provider"))
    async with _test_app(provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "Hi"})

    assert response.status_code == 429


async def test_chat_endpoint_maps_timeout_to_504() -> None:
    """Verify upstream timeouts return HTTP 504."""
    provider = _FakeProvider(error=ProviderTimeoutError("Timed out", provider="fake-provider"))
    async with _test_app(provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "Hi"})

    assert response.status_code == 504
