import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from modules.ai_runtime.retriever import KnowledgeRetriever
from modules.ai_runtime.schemas import ChatTurnInput
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.embeddings import LocalHashEmbeddingProvider
from modules.model_gateway.openai_compatible import _parse_usage
from modules.model_gateway.schemas import (
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    StreamChunk,
    TokenUsage,
)
from modules.tools.cache import ToolResultCache
from modules.tools.registry import ToolRegistry
from modules.tools.schemas import ToolDefinition


class _CountingLLM:
    def __init__(self, responses: list[ModelResponse] | None = None) -> None:
        self.calls = 0
        self._responses = list(responses or [])

    @property
    def provider_name(self) -> str:
        return "counting-llm"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return ModelResponse(
            content="Done.",
            provider=self.provider_name,
            model="mock",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        self.calls += 1
        yield StreamChunk(delta="Done.", finish_reason="stop")


async def test_pre_generate_gate_refuses_without_calling_llm() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            llm = _CountingLLM()
            know = KnowledgeRepository(
                session=session,
                embedding_provider=LocalHashEmbeddingProvider(),
            )
            retriever = KnowledgeRetriever(knowledge_repo=know, llm_provider=llm)
            service = ChatService(
                provider=llm,
                repository=ConversationRepository(session=session),
                retriever=retriever,
            )
            result = await service.execute_turn(
                ChatTurnInput(
                    message="Berapa harga langganan bulan ini?",
                    retrieval_mode="always",
                )
            )
            assert llm.calls == 0
            assert "tidak menemukan informasi ini" in result.reply
            assert result.usage.total_tokens == 0
    finally:
        await engine.dispose()


async def test_parallel_tools_loop_guard_and_ttl_cache() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            exec_count = 0
            registry = ToolRegistry()

            async def _ping(args: dict[str, Any]) -> str:
                nonlocal exec_count
                exec_count += 1
                return json.dumps({"host": args.get("host", "db"), "ok": True})

            registry.register(
                ToolDefinition(
                    name="ping_host",
                    description="Ping a host.",
                    parameters_schema={
                        "type": "object",
                        "properties": {"host": {"type": "string"}},
                    },
                    risk_level="read",
                ),
                _ping,
            )

            llm = _CountingLLM(
                responses=[
                    ModelResponse(
                        content="",
                        provider="counting-llm",
                        model="mock",
                        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                        tool_calls=[
                            ModelToolCall(id="t1", name="ping_host", arguments='{"host":"db1"}'),
                            # Duplicate identical call in same turn -> blocked by loop guard
                            ModelToolCall(id="t2", name="ping_host", arguments='{"host": "db1"}'),
                            ModelToolCall(id="t3", name="ping_host", arguments='{"host":"db2"}'),
                        ],
                    ),
                    ModelResponse(
                        content="Both db1 and db2 are ok.",
                        provider="counting-llm",
                        model="mock",
                        usage=TokenUsage(
                            prompt_tokens=30,
                            completion_tokens=8,
                            total_tokens=38,
                            cached_tokens=20,
                        ),
                    ),
                ]
            )
            service = ChatService(
                provider=llm,
                repository=ConversationRepository(session=session),
                tool_registry=registry,
            )
            res = await service.execute_turn(
                ChatTurnInput(message="Check db1 and db2", retrieval_mode="off")
            )
            assert exec_count == 2
            assert res.tool_calls[1].status == "blocked"
            assert "Duplicate tool call" in res.tool_calls[1].output
            assert res.usage.cached_tokens == 20

            # ToolResultCache direct TTL check
            cache = ToolResultCache(ttl_seconds=60.0)
            cache.set("ping_host", '{"host": "db1"}', '{"ok": true}')
            assert cache.get("ping_host", '{"host":"db1"}') == '{"ok": true}'
    finally:
        await engine.dispose()


def test_parse_usage_extracts_prompt_cache_tokens() -> None:
    openai_style = _parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 80},
        }
    )
    assert openai_style.cached_tokens == 80

    anthropic_style = _parse_usage(
        {
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "total_tokens": 60,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 10,
        }
    )
    assert anthropic_style.cached_tokens == 40
    assert anthropic_style.cache_creation_tokens == 10


async def test_chitchat_hola_skips_knowledge_search() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            llm = _CountingLLM()
            know = KnowledgeRepository(
                session=session,
                embedding_provider=LocalHashEmbeddingProvider(),
            )
            retriever = KnowledgeRetriever(knowledge_repo=know, llm_provider=llm)
            assert retriever.should_search("hola", mode="auto") is False
            assert retriever.should_search("check database failover", mode="auto") is True

            outcome = await retriever.retrieve_with_meta(user_message="hola", mode="auto")
            assert outcome.searched is False
            assert outcome.chunks == []
            assert llm.calls == 0
    finally:
        await engine.dispose()
