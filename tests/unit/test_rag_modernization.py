import json
from typing import Any

import httpx
from pydantic import SecretStr

from core.config.settings import Settings
from modules.ai_runtime.reranker import HeuristicReranker, VoyageRerankProvider, build_reranker
from modules.knowledge.chunker import semantic_chunk_text
from modules.knowledge.schemas import RetrievedChunk
from modules.model_gateway.embeddings import (
    LocalHashEmbeddingProvider,
    OllamaEmbeddingProvider,
    VoyageEmbeddingProvider,
)
from modules.usage.tracing import Tracer


async def test_voyage_embedding_uses_document_and_query_input_types() -> None:
    captured_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(body)
        vecs = [{"index": i, "embedding": [0.5, 0.5]} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": vecs, "usage": {"total_tokens": 8}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = VoyageEmbeddingProvider(
            api_key=SecretStr("sk-voyage-test"),
            embedding_model="voyage-3-lite",
            client=client,
        )
        doc_vecs = await provider.embed_texts(["postgres failover runbook"])
        query_vec = await provider.embed_query("how to failover?")

    assert len(doc_vecs) == 1
    assert query_vec == [0.5, 0.5]
    assert captured_payloads[0]["input_type"] == "document"
    assert captured_payloads[1]["input_type"] == "query"


async def test_ollama_embedding_provider_parses_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "bge-m3"
        return httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2, 0.3]], "prompt_eval_count": 5},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaEmbeddingProvider(
            base_url="http://localhost:11434",
            embedding_model="bge-m3",
            client=client,
        )
        vecs = await provider.embed_texts(["halo dunia"])

    assert vecs == [[0.1, 0.2, 0.3]]


async def test_semantic_chunk_text_splits_on_topic_shift() -> None:
    embedder = LocalHashEmbeddingProvider()
    text = (
        "PostgreSQL uses WAL replication for high availability. "
        "Patroni manages automatic primary failover and leader election. "
        "Kubernetes liveness probes restart unhealthy containers automatically. "
        "Pod resource limits prevent OOMKilled events across cluster nodes."
    )
    chunks = await semantic_chunk_text(
        text,
        embed_fn=embedder.embed_texts,
        document_title="Infra.md",
        min_chunk_chars=60,
        max_chunk_chars=260,
    )
    assert len(chunks) >= 2
    assert all(chunk.startswith("[Doc: Infra.md]") for chunk in chunks)


async def test_reranker_factory_and_voyage_fallback() -> None:
    settings = Settings(_env_file=None, retrieval_reranker="heuristic")
    reranker = build_reranker(settings)
    assert isinstance(reranker, HeuristicReranker)

    voyage = VoyageRerankProvider(api_key="", model="rerank-2-lite")
    cands = [
        RetrievedChunk(
            document_id="d1",
            document_title="Postgres.md",
            chunk_index=0,
            content="Run pg_ctl promote on the standby node.",
            semantic_score=0.7,
            lexical_score=0.6,
            score=0.67,
        )
    ]
    ranked = await voyage.rerank("pg_ctl promote", cands, top_k=1)
    assert len(ranked) == 1
    assert ranked[0].document_id == "d1"


def test_langfuse_tracer_noop_when_disabled() -> None:
    tracer = Tracer(enabled=False)
    assert tracer.active is False
    with tracer.trace("chat_turn", user_id="u1") as tr, tracer.span(tr, "retrieval") as sp:
        sp.update(hits=3)
