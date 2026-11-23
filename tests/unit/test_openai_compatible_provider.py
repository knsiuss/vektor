import json

import httpx
import pytest
from pydantic import SecretStr

from modules.model_gateway.base import LLMProvider
from modules.model_gateway.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from modules.model_gateway.openai_compatible import OpenAICompatibleProvider
from modules.model_gateway.schemas import ChatMessage, ModelRequest


def _sample_request(model: str | None = None) -> ModelRequest:
    return ModelRequest(
        messages=[
            ChatMessage(role="system", content="You are Vektor."),
            ChatMessage(role="user", content="Ping"),
        ],
        model=model,
        temperature=0.1,
        max_tokens=128,
    )


def test_provider_satisfies_llm_provider_protocol() -> None:
    """Verify OpenAICompatibleProvider implements the LLMProvider protocol."""
    provider = OpenAICompatibleProvider(api_key=SecretStr("sk-test-123"))
    assert isinstance(provider, LLMProvider)
    assert provider.provider_name == "openai-compatible"


async def test_generate_success_parses_response_and_usage() -> None:
    """Verify valid completion payload, headers, and normalized response parsing."""
    captured_auth_header: str | None = None
    captured_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_auth_header, captured_body
        captured_auth_header = request.headers.get("Authorization")
        captured_body = json.loads(request.content.decode("utf-8"))
        assert request.url == httpx.URL("https://api.example.com/v1/chat/completions")

        return httpx.Response(
            status_code=200,
            json={
                "id": "chatcmpl-001",
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Pong from Vektor"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 14,
                    "completion_tokens": 4,
                    "total_tokens": 18,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            provider_name="test-openai",
            api_key=SecretStr("sk-secret-key"),
            base_url="https://api.example.com/v1/",
            default_model="gpt-4o-mini",
            client=client,
        )
        result = await provider.generate(_sample_request())

    assert captured_auth_header == "Bearer sk-secret-key"
    assert captured_body["model"] == "gpt-4o-mini"
    assert result.content == "Pong from Vektor"
    assert result.provider == "test-openai"
    assert result.model == "gpt-4o-mini-2024-07-18"
    assert result.finish_reason == "stop"
    assert result.usage.prompt_tokens == 14
    assert result.usage.completion_tokens == 4
    assert result.usage.total_tokens == 18


@pytest.mark.parametrize("api_key", [None, SecretStr(""), SecretStr("   ")])
async def test_generate_fails_closed_without_api_key(api_key: SecretStr | None) -> None:
    """Verify missing or blank API keys raise ProviderAuthenticationError before HTTP call."""
    provider = OpenAICompatibleProvider(api_key=api_key)

    with pytest.raises(ProviderAuthenticationError) as exc_info:
        await provider.generate(_sample_request())

    assert exc_info.value.retryable is False


async def test_generate_maps_401_to_authentication_error() -> None:
    """Verify HTTP 401 is mapped to a non-retryable ProviderAuthenticationError."""
    transport = httpx.MockTransport(lambda _req: httpx.Response(status_code=401))

    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key=SecretStr("sk-bad"), client=client)
        with pytest.raises(ProviderAuthenticationError) as exc_info:
            await provider.generate(_sample_request())

    assert exc_info.value.retryable is False


async def test_generate_maps_429_to_rate_limit_error() -> None:
    """Verify HTTP 429 is mapped to a retryable ProviderRateLimitError."""
    transport = httpx.MockTransport(lambda _req: httpx.Response(status_code=429))

    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key=SecretStr("sk-limit"), client=client)
        with pytest.raises(ProviderRateLimitError) as exc_info:
            await provider.generate(_sample_request())

    assert exc_info.value.retryable is True


async def test_generate_maps_503_to_retryable_response_error() -> None:
    """Verify upstream 5xx responses are marked as retryable ProviderResponseError."""
    transport = httpx.MockTransport(lambda _req: httpx.Response(status_code=503))

    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key=SecretStr("sk-valid"), client=client)
        with pytest.raises(ProviderResponseError) as exc_info:
            await provider.generate(_sample_request())

    assert exc_info.value.retryable is True


async def test_generate_maps_timeout_to_provider_timeout_error() -> None:
    """Verify httpx timeout exceptions translate to retryable ProviderTimeoutError."""

    def raise_timeout(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Simulated read timeout")

    transport = httpx.MockTransport(raise_timeout)

    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            api_key=SecretStr("sk-valid"),
            timeout_seconds=5.0,
            client=client,
        )
        with pytest.raises(ProviderTimeoutError) as exc_info:
            await provider.generate(_sample_request())

    assert exc_info.value.retryable is True


async def test_generate_rejects_malformed_provider_payload() -> None:
    """Verify untrusted/malformed upstream JSON structure raises ProviderResponseError."""
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(status_code=200, json={"unexpected": "shape"})
    )

    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(api_key=SecretStr("sk-valid"), client=client)
        with pytest.raises(ProviderResponseError) as exc_info:
            await provider.generate(_sample_request())

    assert exc_info.value.retryable is False
