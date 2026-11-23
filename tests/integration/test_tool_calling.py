from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.schemas import (
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    StreamChunk,
    TokenUsage,
)
from modules.tools.builtins import build_default_tool_registry
from modules.tools.schemas import ToolDefinition


class _DummyEmbeddings:
    @property
    def embedding_model(self) -> str:
        return "dummy"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class _ToolLoopProvider:
    """Emits a requested tool call on pass 1, then synthesizes the tool output on pass 2."""

    def __init__(self, tool_name: str, arguments: str = "{}") -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "tool-test-llm"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="",
                provider=self.provider_name,
                model="test-model",
                usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                finish_reason="tool_calls",
                tool_calls=[
                    ModelToolCall(
                        id="call_ops_1",
                        name=self._tool_name,
                        arguments=self._arguments,
                    )
                ],
            )

        tool_msg = request.messages[-1].content
        return ModelResponse(
            content=f"Completed after tool output: {tool_msg}",
            provider=self.provider_name,
            model="test-model",
            usage=TokenUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45),
            finish_reason="stop",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="ok", model="test-model")


@asynccontextmanager
async def _tool_client(provider: _ToolLoopProvider) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)

    def _override_chat(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ChatService:
        conv_repo = ConversationRepository(session=session)
        know_repo = KnowledgeRepository(session=session, embedding_provider=_DummyEmbeddings())
        registry = build_default_tool_registry(
            conversation_repo=conv_repo,
            knowledge_repo=know_repo,
        )

        async def _restart_worker(args: dict[str, Any]) -> str:
            return f"Worker {args.get('name', 'default')} restarted."

        registry.register(
            ToolDefinition(
                name="restart_worker",
                description="Restart a background worker process.",
                parameters_schema={"type": "object", "properties": {"name": {"type": "string"}}},
                risk_level="mutating",
            ),
            _restart_worker,
        )
        return ChatService(provider=provider, repository=conv_repo, tool_registry=registry)

    app.dependency_overrides[get_chat_service] = _override_chat

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def test_read_only_tool_executes_and_accumulates_tokens() -> None:
    """Verify read-only built-in tool runs cleanly and aggregates multi-pass tokens."""
    provider = _ToolLoopProvider(tool_name="get_system_health")
    async with _tool_client(provider) as client:
        res = await client.post(
            "/api/v1/chat",
            json={"message": "Check server health", "retrieval_mode": "off"},
        )

    assert res.status_code == 200
    body = res.json()
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["tool_name"] == "get_system_health"
    assert body["tool_calls"][0]["status"] == "success"
    assert "healthy" in body["reply"]
    assert body["usage"]["total_tokens"] == 75


async def test_mutating_and_unlisted_tools_are_blocked_by_default() -> None:
    """Verify mutating tools require explicit approval and unlisted tools are rejected."""
    blocked_provider = _ToolLoopProvider(
        tool_name="restart_worker",
        arguments='{"name": "billing-1"}',
    )
    async with _tool_client(blocked_provider) as client:
        blocked_res = await client.post(
            "/api/v1/chat",
            json={"message": "Restart billing worker", "retrieval_mode": "off"},
        )

    assert blocked_res.status_code == 200
    assert blocked_res.json()["tool_calls"][0]["status"] == "blocked"

    approved_provider = _ToolLoopProvider(
        tool_name="restart_worker",
        arguments='{"name": "billing-1"}',
    )
    async with _tool_client(approved_provider) as client:
        approved_res = await client.post(
            "/api/v1/chat",
            json={
                "message": "Restart billing worker",
                "retrieval_mode": "off",
                "allow_mutating_tools": True,
            },
        )

    assert approved_res.status_code == 200
    assert approved_res.json()["tool_calls"][0]["status"] == "success"
    assert "restarted" in approved_res.json()["reply"]
