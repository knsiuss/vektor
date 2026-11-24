from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_chat_service_factory, get_db_session
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.model_gateway.schemas import ModelRequest, ModelResponse, StreamChunk, TokenUsage


class _ScriptedProvider:
    """Returns one scripted reply per turn so tests can drive status transitions."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self._index = 0

    @property
    def provider_name(self) -> str:
        return "scripted"

    def _next(self) -> str:
        reply = self._replies[min(self._index, len(self._replies) - 1)]
        self._index += 1
        return reply

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content=self._next(),
            provider=self.provider_name,
            model=request.model or "scripted-model",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        for word in self._next().split(" "):
            yield StreamChunk(delta=f"{word} ", model=request.model or "scripted-model")
        yield StreamChunk(
            delta="",
            model=request.model or "scripted-model",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            finish_reason="stop",
        )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        name = ""
        payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                payload += line[6:]
        if name:
            import json

            events.append((name, json.loads(payload) if payload else {}))
    return events


@asynccontextmanager
async def _client(provider: _ScriptedProvider) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)

    def _override(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ChatService:
        return ChatService(
            provider=provider,
            repository=ConversationRepository(session=session),
        )

    def _override_factory():
        def _factory(session: AsyncSession) -> ChatService:
            return ChatService(
                provider=provider,
                repository=ConversationRepository(session=session),
            )

        return _factory

    app.dependency_overrides[get_chat_service] = _override
    app.dependency_overrides[get_chat_service_factory] = _override_factory

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def test_stream_clarify_hides_the_marker_and_persists_options() -> None:
    """The reader must never see the envelope marker; the question arrives as a result event."""
    provider = _ScriptedProvider(
        ['<<status=clarify>> {"question": "Toko mana?", "options": ["Tangsel", "Jakarta"]}']
    )
    async with _client(provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "omzet bulan lalu"})
        events = _parse_sse(response.text)
        conversation_id = next(data for name, data in events if name == "meta")["conversation_id"]

        result = next(data for name, data in events if name == "result")
        deltas = "".join(data.get("delta", "") for name, data in events if name == "delta")
        detail = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()

    assert result["status"] == "clarify"
    assert result["options"] == ["Tangsel", "Jakarta"]
    assert "status=" not in deltas
    assert "Toko mana?" in deltas
    persisted = detail["messages"][-1]
    assert persisted["status"] == "clarify"
    assert persisted["clarify_options"] == ["Tangsel", "Jakarta"]


async def test_third_consecutive_clarification_degrades_to_unknown() -> None:
    """Two questions are tolerated; the third turn must not ask again."""
    provider = _ScriptedProvider(
        [
            '<<status=clarify>> {"question": "Toko mana?", "options": ["Tangsel"]}',
            '<<status=clarify>> {"question": "Periode apa?", "options": ["Bulan ini"]}',
            '<<status=clarify>> {"question": "Sekali lagi, toko mana?"}',
        ]
    )
    async with _client(provider) as client:
        started = await client.post("/api/v1/chat/stream", json={"message": "omzet"})
        first = _parse_sse(started.text)
        conversation_id = next(data for name, data in first if name == "meta")["conversation_id"]
        await client.post(
            "/api/v1/chat/stream",
            json={"message": "toko tangsel", "conversation_id": conversation_id},
        )
        answered = await client.post(
            "/api/v1/chat/stream",
            json={"message": "bulan ini", "conversation_id": conversation_id},
        )
        third = _parse_sse(answered.text)
        detail = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()

    statuses = [data.get("status") for name, data in third if name == "result"]
    assert statuses[-1] == "unknown"
    assert detail["messages"][-1]["status"] == "unknown"
    assert detail["messages"][-1]["clarify_options"] is None


async def test_non_streaming_turn_reports_the_envelope() -> None:
    """The plain JSON endpoint exposes status fields without breaking `reply`."""
    provider = _ScriptedProvider(["<<status=unknown>> Tidak ada data runbook failover."])
    async with _client(provider) as client:
        response = await client.post("/api/v1/chat", json={"message": "runbook failover?"})

    body = response.json()
    assert body["status"] == "unknown"
    assert body["reply"] == "Tidak ada data runbook failover."
    assert body["options"] == []


async def test_markerless_reply_stays_a_plain_answer() -> None:
    """Old-style output keeps working: no marker, no status surprise."""
    provider = _ScriptedProvider(["Replication lag is 4 seconds."])
    async with _client(provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "lag?"})
        events = _parse_sse(response.text)

    deltas = "".join(data.get("delta", "") for name, data in events if name == "delta")
    statuses = [data.get("status") for name, data in events if name == "result"]
    assert deltas.strip() == "Replication lag is 4 seconds."
    assert statuses in ([], ["answer"])


async def test_usage_summary_counts_reply_statuses() -> None:
    """Telemetry must be able to report how often the assistant asked instead of answering."""
    provider = _ScriptedProvider(
        [
            '<<status=clarify>> {"question": "Toko mana?", "options": ["Tangsel"]}',
            "<<status=answer>> Omzet Tangsel naik 4%.",
        ]
    )
    async with _client(provider) as client:
        started = await client.post("/api/v1/chat/stream", json={"message": "omzet?"})
        conversation_id = next(
            data for name, data in _parse_sse(started.text) if name == "meta"
        )["conversation_id"]
        await client.post(
            "/api/v1/chat/stream",
            json={"message": "toko tangsel", "conversation_id": conversation_id},
        )
        usage = (await client.get("/api/v1/usage")).json()

    assert usage["by_status"]["clarify"] == 1
    assert usage["by_status"]["answer"] == 1
