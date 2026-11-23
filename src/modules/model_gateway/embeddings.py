from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import SecretStr

from modules.model_gateway.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contract for generating dense vector embeddings from text inputs."""

    @property
    def embedding_model(self) -> str:
        """Identifier of the active embedding model."""
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized embedding vectors for a batch of text strings."""
        ...


class OpenAICompatibleEmbeddingProvider:
    """Async adapter for OpenAI-compatible /embeddings endpoints."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        provider_name: str = "openai-compatible",
        base_url: str = "https://api.openai.com/v1",
        embedding_model: str = "text-embedding-3-small",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._embedding_model = embedding_model
        self._timeout_seconds = timeout_seconds
        self._external_client = client

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        raw_key = self._resolve_api_key()
        payload: dict[str, Any] = {
            "model": self._embedding_model,
            "input": texts,
        }
        raw_data = await self._post_json("/embeddings", payload, raw_key)
        return self._parse_embeddings(raw_data, expected_count=len(texts))

    def _resolve_api_key(self) -> str:
        if self._api_key is None:
            raise ProviderAuthenticationError(
                "Missing API key for embedding provider.",
                provider=self._provider_name,
            )
        raw_value = self._api_key.get_secret_value().strip()
        if not raw_value:
            raise ProviderAuthenticationError(
                "Blank API key provided for embedding provider.",
                provider=self._provider_name,
            )
        return raw_value

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        raw_key: str,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {raw_key}",
            "Content-Type": "application/json",
        }
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
                "Upstream embedding request timed out.",
                provider=self._provider_name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                "Network error communicating with upstream embedding provider.",
                provider=self._provider_name,
                retryable=True,
            ) from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(
                "Upstream embedding authentication failed.",
                provider=self._provider_name,
            )
        if response.status_code == 429:
            raise ProviderRateLimitError(
                "Upstream embedding rate limit exceeded.",
                provider=self._provider_name,
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"Upstream embedding returned HTTP {response.status_code}.",
                provider=self._provider_name,
                retryable=response.status_code >= 500,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "Upstream embedding returned invalid JSON.",
                provider=self._provider_name,
            ) from exc

        if not isinstance(data, dict):
            raise ProviderResponseError(
                "Upstream embedding returned unexpected payload structure.",
                provider=self._provider_name,
            )
        return data

    def _parse_embeddings(
        self,
        raw_data: dict[str, Any],
        *,
        expected_count: int,
    ) -> list[list[float]]:
        items = raw_data.get("data")
        if not isinstance(items, list) or len(items) != expected_count:
            raise ProviderResponseError(
                "Upstream embedding count did not match input batch size.",
                provider=self._provider_name,
            )

        sorted_items = sorted(
            items,
            key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0,
        )
        vectors: list[list[float]] = []
        for item in sorted_items:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise ProviderResponseError(
                    "Upstream embedding entry missing numeric vector.",
                    provider=self._provider_name,
                )
            vectors.append([float(val) for val in item["embedding"]])
        return vectors
