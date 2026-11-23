import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import SecretStr

from modules.model_gateway.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from modules.model_gateway.schemas import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    StreamChunk,
    TokenUsage,
)


class OpenAICompatibleProvider:
    """Async adapter for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        provider_name: str = "openai-compatible",
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
        self._external_client = client

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raw_key = self._resolve_api_key()
        resolved_model = request.model or self._default_model
        payload = self._build_payload(request, resolved_model, stream=False)

        raw_data = await self._post_json("/chat/completions", payload, raw_key)
        return self._parse_response(raw_data, resolved_model)

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        raw_key = self._resolve_api_key()
        resolved_model = request.model or self._default_model
        payload = self._build_payload(request, resolved_model, stream=True)

        async for chunk in self._stream_sse("/chat/completions", payload, raw_key, resolved_model):
            yield chunk

    def _resolve_api_key(self) -> str:
        if self._api_key is None:
            raise ProviderAuthenticationError(
                "Missing API key for LLM provider.",
                provider=self._provider_name,
            )
        raw_value = self._api_key.get_secret_value().strip()
        if not raw_value:
            raise ProviderAuthenticationError(
                "Blank API key provided for LLM provider.",
                provider=self._provider_name,
            )
        return raw_value

    def _build_headers(self, raw_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {raw_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        request: ModelRequest,
        resolved_model: str,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [self._serialize_message(msg) for msg in request.messages],
            "temperature": request.temperature,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = request.tools
        return payload

    def _serialize_message(self, msg: ChatMessage) -> dict[str, Any]:
        serialized: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            serialized["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in msg.tool_calls
            ]
        return serialized

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        raw_key: str,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = self._build_headers(raw_key)

        try:
            if self._external_client is not None:
                response = await self._external_client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Upstream LLM request timed out.",
                provider=self._provider_name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                "Network error communicating with upstream LLM provider.",
                provider=self._provider_name,
                retryable=True,
            ) from exc

        self._raise_for_status(response.status_code)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "Upstream LLM returned invalid JSON.",
                provider=self._provider_name,
            ) from exc

        if not isinstance(data, dict):
            raise ProviderResponseError(
                "Upstream LLM returned unexpected payload structure.",
                provider=self._provider_name,
            )
        return data

    async def _stream_sse(
        self,
        path: str,
        payload: dict[str, Any],
        raw_key: str,
        fallback_model: str,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self._base_url}{path}"
        headers = self._build_headers(raw_key)

        try:
            if self._external_client is not None:
                async with self._external_client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                ) as response:
                    self._raise_for_status(response.status_code)
                    async for chunk in self._iter_sse_lines(response, fallback_model):
                        yield chunk
            else:
                async with (
                    httpx.AsyncClient(timeout=self._timeout_seconds) as client,
                    client.stream("POST", url, json=payload, headers=headers) as response,
                ):
                    self._raise_for_status(response.status_code)
                    async for chunk in self._iter_sse_lines(response, fallback_model):
                        yield chunk
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Upstream LLM stream timed out.",
                provider=self._provider_name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                "Network error during upstream LLM stream.",
                provider=self._provider_name,
                retryable=True,
            ) from exc

    async def _iter_sse_lines(
        self,
        response: httpx.Response,
        fallback_model: str,
    ) -> AsyncIterator[StreamChunk]:
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            chunk = self._parse_stream_chunk(data_str, fallback_model)
            if chunk is not None:
                yield chunk

    def _parse_stream_chunk(self, data_str: str, fallback_model: str) -> StreamChunk | None:
        try:
            data = json.loads(data_str)
        except ValueError as exc:
            raise ProviderResponseError(
                "Upstream LLM emitted malformed SSE JSON.",
                provider=self._provider_name,
            ) from exc

        if not isinstance(data, dict):
            return None

        model_name = data.get("model")
        resolved_model = (
            model_name if isinstance(model_name, str) and model_name else fallback_model
        )

        usage: TokenUsage | None = None
        raw_usage = data.get("usage")
        if isinstance(raw_usage, dict):
            usage = TokenUsage(
                prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                total_tokens=int(raw_usage.get("total_tokens", 0)),
            )

        delta_text = ""
        finish_reason: str | None = None
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            delta = choices[0].get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                delta_text = delta["content"]
            raw_finish = choices[0].get("finish_reason")
            if isinstance(raw_finish, str):
                finish_reason = raw_finish

        if not delta_text and usage is None and finish_reason is None:
            return None

        return StreamChunk(
            delta=delta_text,
            model=resolved_model,
            usage=usage,
            finish_reason=finish_reason,
        )

    def _raise_for_status(self, status_code: int) -> None:
        if status_code in (401, 403):
            raise ProviderAuthenticationError(
                "Upstream LLM rejected authentication credentials.",
                provider=self._provider_name,
            )
        if status_code == 429:
            raise ProviderRateLimitError(
                "Upstream LLM rate limit exceeded.",
                provider=self._provider_name,
            )
        if status_code >= 400:
            raise ProviderResponseError(
                f"Upstream LLM returned HTTP {status_code}.",
                provider=self._provider_name,
                retryable=status_code >= 500,
            )

    def _parse_response(self, raw_data: dict[str, Any], fallback_model: str) -> ModelResponse:
        choices = raw_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError(
                "Upstream LLM response contained no choices.",
                provider=self._provider_name,
            )

        first_choice = choices[0]
        message = first_choice.get("message") if isinstance(first_choice, dict) else None
        if not isinstance(message, dict):
            raise ProviderResponseError(
                "Upstream LLM choice missing message object.",
                provider=self._provider_name,
            )

        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif tool_calls:
            content = ""
        else:
            raise ProviderResponseError(
                "Upstream LLM choice missing text content.",
                provider=self._provider_name,
            )

        raw_usage = raw_data.get("usage")
        usage = TokenUsage()
        if isinstance(raw_usage, dict):
            usage = TokenUsage(
                prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                total_tokens=int(raw_usage.get("total_tokens", 0)),
            )

        model_name = raw_data.get("model")
        resolved_model = (
            model_name if isinstance(model_name, str) and model_name else fallback_model
        )

        return ModelResponse(
            content=content,
            provider=self._provider_name,
            model=resolved_model,
            usage=usage,
            finish_reason=(
                first_choice.get("finish_reason") if isinstance(first_choice, dict) else None
            ),
            tool_calls=tool_calls,
        )

    def _parse_tool_calls(self, raw_calls: Any) -> list[ModelToolCall]:
        if not isinstance(raw_calls, list):
            return []
        parsed: list[ModelToolCall] = []
        for idx, item in enumerate(raw_calls):
            if not isinstance(item, dict):
                continue
            fn = item.get("function")
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            if not isinstance(name, str) or not name:
                continue
            call_id = item.get("id")
            resolved_id = call_id if isinstance(call_id, str) and call_id else f"call_{idx}"
            raw_args = fn.get("arguments")
            args_str = raw_args if isinstance(raw_args, str) else json.dumps(raw_args or {})
            parsed.append(ModelToolCall(id=resolved_id, name=name, arguments=args_str))
        return parsed
