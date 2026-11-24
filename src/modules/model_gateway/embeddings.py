import asyncio
import hashlib
import math
import re
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import SecretStr

from modules.model_gateway.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)

_EMBED_BATCH_SIZE = 64


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
        on_usage: Callable[[str, int, int, int], None] | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._embedding_model = embedding_model
        self._timeout_seconds = timeout_seconds
        self._external_client = client
        self._on_usage = on_usage

    def _report_usage(self, raw_data: dict[str, Any]) -> None:
        if self._on_usage is None:
            return
        prompt = total = 0
        usage = raw_data.get("usage")
        if isinstance(usage, dict):
            prompt = int(usage.get("prompt_tokens", 0) or 0)
            total = int(usage.get("total_tokens", prompt) or 0)
        self._on_usage(self._embedding_model, prompt, 0, total)

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        raw_key = self._resolve_api_key()
        vectors: list[list[float]] = []
        # Providers cap how many inputs one request may carry, so send fixed-size batches.
        for start in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[start : start + _EMBED_BATCH_SIZE]
            payload: dict[str, Any] = {
                "model": self._embedding_model,
                "input": batch,
            }
            raw_data = await self._post_json("/embeddings", payload, raw_key)
            vectors.extend(self._parse_embeddings(raw_data, expected_count=len(batch)))
        return vectors

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


def _extract_upstream_error(response: httpx.Response) -> str:
    """Extract a concise, secret-free error summary from an HTTP error response."""
    detail = ""
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str) and msg.strip():
                detail = msg.strip()
        elif isinstance(err, str) and err.strip():
            detail = err.strip()
        if not detail:
            for key in ("message", "detail"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    detail = val.strip()
                    break
    if not detail:
        text = response.text.strip()
        if text:
            detail = text
    return " ".join(detail.split())[:200]


_LOCAL_DIM = 384
_WORD_RE = re.compile(r"[a-z0-9]+")


class LocalHashEmbeddingProvider:
    """Zero-cost deterministic local embedding provider using signed feature hashing."""

    def __init__(self, embedding_model: str = "local-hash-v1", dim: int = _LOCAL_DIM) -> None:
        self._embedding_model = embedding_model
        self._dim = dim

    @property
    def embedding_model(self) -> str:
        """Identifier of the active local embedding model."""
        return self._embedding_model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate L2-normalized 384-dim feature-hashed vectors for text inputs."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        normalized = " ".join(text.lower().split())
        if not normalized:
            return vec

        words = _WORD_RE.findall(normalized)
        for word in words:
            self._add_feature(vec, f"w:{word}", 1.5)
        for token in words:
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    self._add_feature(vec, f"c:{token[i : i + 3]}", 1.0)
            else:
                self._add_feature(vec, f"c:{token}", 1.0)

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            inv = 1.0 / norm
            vec = [v * inv for v in vec]
        return vec

    def _add_feature(self, vec: list[float], feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        val = int.from_bytes(digest, "little")
        idx = (val >> 1) % self._dim
        sign = 1.0 if (val & 1) else -1.0
        vec[idx] += sign * weight


class VoyageEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    """Adapter for Voyage AI /v1/embeddings with document vs query input_type."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        provider_name: str = "voyage",
        base_url: str = "https://api.voyageai.com/v1",
        embedding_model: str = "voyage-3-lite",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        on_usage: Callable[[str, int, int, int], None] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            provider_name=provider_name,
            base_url=base_url,
            embedding_model=embedding_model,
            timeout_seconds=timeout_seconds,
            client=client,
            on_usage=on_usage,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_with_type(texts, input_type="document")

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed_with_type([text], input_type="query")
        return vectors[0]

    async def _embed_with_type(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        if not texts:
            return []
        raw_key = self._resolve_api_key()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[start : start + _EMBED_BATCH_SIZE]
            payload: dict[str, Any] = {
                "model": self._embedding_model,
                "input": batch,
                "input_type": input_type,
            }
            raw_data = await self._post_json("/embeddings", payload, raw_key)
            self._report_usage(raw_data)
            vectors.extend(self._parse_embeddings(raw_data, expected_count=len(batch)))
        return vectors


class OllamaEmbeddingProvider:
    """OS-agnostic local embedding provider via Ollama (/api/embed, e.g. bge-m3)."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        embedding_model: str = "bge-m3",
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
        on_usage: Callable[[str, int, int, int], None] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._embedding_model = embedding_model
        self._timeout_seconds = timeout_seconds
        self._external_client = client
        self._on_usage = on_usage

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[start : start + _EMBED_BATCH_SIZE]
            payload = {"model": self._embedding_model, "input": batch}
            raw_data = await self._post_embed(payload)
            raw_vecs = raw_data.get("embeddings")
            if not isinstance(raw_vecs, list) or len(raw_vecs) != len(batch):
                raise ProviderResponseError(
                    "Ollama /api/embed response missing expected embeddings list.",
                    provider="ollama",
                )
            for vec in raw_vecs:
                if not isinstance(vec, list):
                    raise ProviderResponseError(
                        "Ollama embedding entry is not a vector.",
                        provider="ollama",
                    )
                vectors.append([float(val) for val in vec])
            if self._on_usage is not None:
                prompt_tokens = int(raw_data.get("prompt_eval_count", 0) or 0)
                self._on_usage(self._embedding_model, prompt_tokens, 0, prompt_tokens)
        return vectors

    async def _post_embed(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/api/embed"
        try:
            if self._external_client is not None:
                response = await self._external_client.post(
                    url,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Ollama embedding request timed out.",
                provider="ollama",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                f"Cannot reach Ollama at {self._base_url}. Ensure Ollama is running.",
                provider="ollama",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            detail = _extract_upstream_error(response)
            msg = (
                f"Ollama embedding returned HTTP {response.status_code}: {detail}"
                if detail
                else f"Ollama embedding returned HTTP {response.status_code}."
            )
            raise ProviderResponseError(
                msg,
                provider="ollama",
                retryable=response.status_code >= 500,
            )
        data = response.json()
        if not isinstance(data, dict):
            raise ProviderResponseError("Ollama returned non-object JSON.", provider="ollama")
        return data


class LocalBGEEmbeddingProvider:
    """Native Python local embedding provider using sentence-transformers (CUDA/MPS/CPU)."""

    def __init__(
        self,
        *,
        embedding_model: str = "BAAI/bge-m3",
        device: str | None = None,
    ) -> None:
        self._embedding_model = embedding_model
        self._device = device
        self._model: Any = None

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import torch  # type: ignore[import-not-found]
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderResponseError(
                "Local BGE embedding requires optional dependencies: "
                "pip install 'vektor[local-ml]'.",
                provider="local-bge",
            ) from exc

        device = self._device
        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self._model = SentenceTransformer(self._embedding_model, device=device)
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def _encode() -> list[list[float]]:
            model = self._get_model()
            arr = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return [[float(x) for x in row] for row in arr.tolist()]

        return await asyncio.to_thread(_encode)
