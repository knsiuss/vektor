from typing import Any

import httpx
from pydantic import SecretStr

from modules.model_gateway.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from modules.model_gateway.schemas import ModelRequest, ModelResponse, TokenUsage


class OpenAICompatibleProvider:
    """Async LLM provider adapter for OpenAI-compatible /chat/completions endpoints."""

    def __init__(
        self,
        *,
        provider_name: str = "openai-compatible",
        api_key: SecretStr | None,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4o-mini",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def provider_name(self) -> str:
        """Return the canonical identifier of this provider."""
        return self._provider_name

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Send a chat completion request and return a normalized ModelResponse."""
        secret_key = self._resolve_api_key()
        target_model = request.model or self._default_model
        url = f"{self._base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        response = await self._send_request(url=url, headers=headers, payload=payload)
        return self._parse_response(response=response, fallback_model=target_model)

    def _resolve_api_key(self) -> str:
        """Validate that an API key is configured before making an external call."""
        if self._api_key is None:
            raise ProviderAuthenticationError(
                f"API key is not configured for provider '{self._provider_name}'.",
                provider=self._provider_name,
            )
        value = self._api_key.get_secret_value().strip()
        if not value:
            raise ProviderAuthenticationError(
                f"API key is empty for provider '{self._provider_name}'.",
                provider=self._provider_name,
            )
        return value

    async def _send_request(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        """Execute the HTTP POST request and translate transport errors."""
        try:
            if self._client is not None:
                return await self._client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as temp_client:
                return await temp_client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Request to provider '{self._provider_name}' timed out after "
                f"{self._timeout_seconds}s.",
                provider=self._provider_name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                f"Network transport error communicating with provider '{self._provider_name}'.",
                provider=self._provider_name,
                retryable=True,
            ) from exc

    def _parse_response(self, *, response: httpx.Response, fallback_model: str) -> ModelResponse:
        """Validate HTTP status and extract normalized content and token usage."""
        status = response.status_code

        if status in (401, 403):
            raise ProviderAuthenticationError(
                f"Authentication failed with provider '{self._provider_name}' (HTTP {status}).",
                provider=self._provider_name,
            )
        if status == 429:
            raise ProviderRateLimitError(
                f"Rate limit exceeded for provider '{self._provider_name}' (HTTP 429).",
                provider=self._provider_name,
            )
        if status >= 500:
            raise ProviderResponseError(
                f"Upstream server error from provider '{self._provider_name}' (HTTP {status}).",
                provider=self._provider_name,
                retryable=True,
            )
        if status >= 400:
            raise ProviderResponseError(
                f"Provider '{self._provider_name}' rejected request (HTTP {status}).",
                provider=self._provider_name,
                retryable=False,
            )

        try:
            raw_data: Any = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"Provider '{self._provider_name}' returned invalid JSON.",
                provider=self._provider_name,
                retryable=False,
            ) from exc

        if not isinstance(raw_data, dict):
            raise ProviderResponseError(
                f"Provider '{self._provider_name}' returned unexpected root payload type.",
                provider=self._provider_name,
                retryable=False,
            )

        choices = raw_data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderResponseError(
                f"Provider '{self._provider_name}' response missing valid 'choices' list.",
                provider=self._provider_name,
                retryable=False,
            )

        first_choice: dict[str, Any] = choices[0]
        message = first_choice.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderResponseError(
                f"Provider '{self._provider_name}' response missing text message content.",
                provider=self._provider_name,
                retryable=False,
            )

        usage_raw = raw_data.get("usage")
        usage = self._parse_usage(usage_raw)

        resolved_model = raw_data.get("model")
        model_name = (
            resolved_model
            if isinstance(resolved_model, str) and resolved_model.strip()
            else fallback_model
        )

        finish_reason_raw = first_choice.get("finish_reason")
        finish_reason = finish_reason_raw if isinstance(finish_reason_raw, str) else None

        return ModelResponse(
            content=message["content"],
            provider=self._provider_name,
            model=model_name,
            usage=usage,
            finish_reason=finish_reason,
        )

    @staticmethod
    def _parse_usage(usage_raw: Any) -> TokenUsage:
        """Safely extract non-negative integer token counts from provider usage metadata."""
        if not isinstance(usage_raw, dict):
            return TokenUsage()

        prompt = usage_raw.get("prompt_tokens")
        completion = usage_raw.get("completion_tokens")
        total = usage_raw.get("total_tokens")

        prompt_tokens = prompt if isinstance(prompt, int) and prompt >= 0 else 0
        completion_tokens = completion if isinstance(completion, int) and completion >= 0 else 0
        total_tokens = (
            total if isinstance(total, int) and total >= 0 else (prompt_tokens + completion_tokens)
        )

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
