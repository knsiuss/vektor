import asyncio
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import httpx

from modules.knowledge.schemas import RetrievedChunk

_WORD_RE = re.compile(r"[a-z0-9_.-]+")
_TECH_TOKEN_RE = re.compile(r"\b(?:[a-z0-9]+[-_./][a-z0-9_./-]+|[A-Z]{2,}[_-][A-Z0-9_-]+)\b")


def rerank_chunks(
    query: str,
    candidates: Sequence[RetrievedChunk],
    *,
    top_k: int = 4,
) -> list[RetrievedChunk]:
    """Stage-2 cross-scoring reranker over Stage-1 hybrid candidates.

    Combines Stage-1 RRF/semantic+BM25 score with exact technical identifier overlap,
    title/section alignment, and contiguous bigram phrase matches.
    """
    if not candidates:
        return []

    q_lower = query.lower()
    q_words = _WORD_RE.findall(q_lower)
    bigrams = {
        f"{q_words[i]} {q_words[i + 1]}"
        for i in range(len(q_words) - 1)
        if len(q_words[i]) > 2 and len(q_words[i + 1]) > 2
    }
    tech_tokens = {tok.lower() for tok in _TECH_TOKEN_RE.findall(query)}

    scored: list[tuple[float, RetrievedChunk]] = []
    for chunk in candidates:
        body_lower = chunk.content.lower()
        section = getattr(chunk, "section", "") or ""
        header_lower = f"{chunk.document_title} {section}".lower()

        bigram_hits = sum(1 for bg in bigrams if bg in body_lower)
        bigram_bonus = min(0.15, (bigram_hits / len(bigrams)) * 0.15) if bigrams else 0.0

        tech_hits = sum(1 for tok in tech_tokens if tok in body_lower)
        tech_bonus = min(0.20, (tech_hits / len(tech_tokens)) * 0.20) if tech_tokens else 0.0

        header_hits = sum(1 for w in set(q_words) if len(w) > 2 and w in header_lower)
        header_bonus = min(0.10, header_hits * 0.035)

        rerank_score = min(1.0, chunk.score + bigram_bonus + tech_bonus + header_bonus)
        scored.append((rerank_score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _score, chunk in scored[:top_k]]


@runtime_checkable
class Reranker(Protocol):
    """Contract for Stage-2 candidate rerankers."""

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        *,
        top_k: int = 4,
    ) -> list[RetrievedChunk]:
        """Re-score and return the top_k most relevant candidates."""
        ...


class HeuristicReranker:
    """Zero-latency Stage-2 heuristic reranker."""

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        *,
        top_k: int = 4,
    ) -> list[RetrievedChunk]:
        return rerank_chunks(query, candidates, top_k=top_k)


class VoyageRerankProvider:
    """Stage-2 neural reranker via Voyage AI /v1/rerank with heuristic fallback."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "rerank-2-lite",
        base_url: str = "https://api.voyageai.com/v1",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._api_key = api_key.strip()
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        *,
        top_k: int = 4,
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        if not self._api_key:
            return rerank_chunks(query, candidates, top_k=top_k)

        payload = {
            "model": self._model,
            "query": query,
            "documents": [c.content for c in candidates],
            "top_k": min(top_k, len(candidates)),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/rerank",
                    json=payload,
                    headers=headers,
                )
            if response.status_code >= 400:
                return rerank_chunks(query, candidates, top_k=top_k)
            data = response.json()
            results = data.get("data")
            if not isinstance(results, list):
                return rerank_chunks(query, candidates, top_k=top_k)
            reranked: list[RetrievedChunk] = []
            for item in results[:top_k]:
                if not isinstance(item, dict):
                    continue
                idx = int(item.get("index", -1))
                if 0 <= idx < len(candidates):
                    base = candidates[idx]
                    rel = float(item.get("relevance_score", base.score))
                    reranked.append(base.model_copy(update={"score": round(rel, 4)}))
            return reranked or rerank_chunks(query, candidates, top_k=top_k)
        except (httpx.HTTPError, ValueError):
            return rerank_chunks(query, candidates, top_k=top_k)


class LocalBGEReranker:
    """Native local CrossEncoder reranker (BAAI/bge-reranker-v2-m3) with CUDA/MPS/CPU."""

    def __init__(
        self,
        *,
        model: str = "BAAI/bge-reranker-v2-m3",
        device: str | None = None,
    ) -> None:
        self._model_name = model
        self._device = device
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        import torch  # type: ignore[import-not-found]
        from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

        device = self._device
        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self._model = CrossEncoder(self._model_name, device=device)
        return self._model

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        *,
        top_k: int = 4,
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []

        def _predict() -> list[RetrievedChunk]:
            model = self._get_model()
            pairs = [(query, c.content) for c in candidates]
            scores = model.predict(pairs, show_progress_bar=False)
            scored: list[tuple[float, RetrievedChunk]] = []
            for raw_score, chunk in zip(scores, candidates, strict=True):
                prob = 1.0 / (1.0 + math.exp(-float(raw_score)))
                scored.append((prob, chunk.model_copy(update={"score": round(prob, 4)})))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [chunk for _score, chunk in scored[:top_k]]

        return await asyncio.to_thread(_predict)


def build_reranker(settings: Any) -> Reranker:
    """Construct the configured Stage-2 reranker from application Settings."""
    mode = getattr(settings, "retrieval_reranker", "heuristic")
    model = getattr(settings, "retrieval_reranker_model", None)
    if mode == "voyage":
        secret = getattr(settings, "retrieval_reranker_api_key", None) or getattr(
            settings, "resolved_embedding_api_key", None
        )
        raw_key = secret.get_secret_value() if secret is not None else ""
        return VoyageRerankProvider(
            api_key=raw_key,
            model=model or "rerank-2-lite",
        )
    if mode == "local-bge":
        return LocalBGEReranker(model=model or "BAAI/bge-reranker-v2-m3")
    return HeuristicReranker()
