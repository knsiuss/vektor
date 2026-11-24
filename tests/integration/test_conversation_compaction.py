from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    get_chat_service,
    get_conversation_compactor,
    get_db_session,
)
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.compaction import ConversationCompactor
from modules.conversations.repository import ConversationRepository
from modules.model_gateway.schemas import ModelRequest, ModelResponse, StreamChunk, TokenUsage


class _StubProvider:
    def __init__(
        self,
        summary: str = "- user asked about logs\n- assistant answered",
        *,
        reply_for_chat: bool = False,
    ) -> None:
        self._summary = "Recorded reply." if reply_for_chat else summary
        self.generate_calls = 0

    @property
    def provider_name(self) -> str:
        return "stub-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.generate_calls += 1
        return ModelResponse(
            content=self._summary,
            provider=self.provider_name,
            model=request.model or "stub-model",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(
            delta="Recorded reply.",
            model=request.model or "stub-model",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )


@asynccontextmanager
async def _test_client(provider: _StubProvider) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)

    def _override_chat(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ChatService:
        # Separate stub so `provider.generate_calls` only counts compaction work.
        return ChatService(
            provider=_StubProvider(reply_for_chat=True),
            repository=ConversationRepository(session=session),
        )

    def _override_compactor(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ConversationCompactor:
        return ConversationCompactor(
            provider=provider,
            repository=ConversationRepository(session=session),
        )

    app.dependency_overrides[get_chat_service] = _override_chat
    app.dependency_overrides[get_conversation_compactor] = _override_compactor

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def _seed_turns(client: httpx.AsyncClient, turns: int) -> str:
    conversation_id = ""
    for index in range(turns):
        response = await client.post(
            "/api/v1/chat",
            json={
                "message": f"Question {index} about replication lag?",
                "conversation_id": conversation_id or None,
            },
        )
        assert response.status_code == 200
        conversation_id = response.json()["conversation_id"]
    return conversation_id


async def test_detail_reports_prompt_window_usage() -> None:
    """Detail responses expose how many tokens the replayable history occupies."""
    async with _test_client(_StubProvider()) as client:
        conversation_id = await _seed_turns(client, turns=1)
        detail = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()

    context = detail["context"]
    assert context["total_messages"] == 2
    assert context["included_messages"] == 2
    assert context["limit_tokens"] == 3500
    assert context["used_tokens"] > 0


async def test_compact_replaces_old_turns_with_a_summary() -> None:
    """Older turns collapse into one summary message while the newest turns survive."""
    provider = _StubProvider()
    async with _test_client(provider) as client:
        conversation_id = await _seed_turns(client, turns=4)
        before = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()

        response = await client.post(f"/api/v1/conversations/{conversation_id}/compact")
        assert response.status_code == 200
        after = response.json()

        assert provider.generate_calls == 1
        roles = [message["role"] for message in after["messages"]]
        assert roles[0] == "summary"
        assert roles.count("summary") == 1
        assert len(after["messages"]) < len(before["messages"])
        assert after["messages"][-1]["role"] == "assistant"
        assert after["context"]["used_tokens"] <= before["context"]["used_tokens"]


async def test_compact_leaves_short_conversations_untouched() -> None:
    """A conversation within the keep-last window is returned without a provider call."""
    provider = _StubProvider()
    async with _test_client(provider) as client:
        conversation_id = await _seed_turns(client, turns=1)
        before = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()

        response = await client.post(f"/api/v1/conversations/{conversation_id}/compact")
        after = response.json()

    assert response.status_code == 200
    assert provider.generate_calls == 0
    assert after["messages"] == before["messages"]


async def test_compact_unknown_conversation_returns_404() -> None:
    """Compacting a missing conversation reports 404 instead of creating one."""
    async with _test_client(_StubProvider()) as client:
        response = await client.post("/api/v1/conversations/missing-id/compact")

    assert response.status_code == 404
