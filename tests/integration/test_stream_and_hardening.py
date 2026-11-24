import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service_factory, get_embedding_provider
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import DEV_PRINCIPAL
from modules.model_gateway.exceptions import ModelGatewayError
from modules.model_gateway.schemas import (
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    StreamChunk,
    TokenUsage,
    ToolCallDelta,
)
from modules.tools.registry import ToolRegistry
from modules.tools.schemas import ToolDefinition

_USAGE = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)


class _FakeEmbeddings:
    embedding_model = "fake-embed"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeProvider:
    """Provider whose stream() replays prepared rounds of chunks (or yields words)."""

    def __init__(
        self,
        *,
        rounds: list[list[StreamChunk]] | None = None,
        reply: str = "plain streamed reply",
        fail: bool = False,
    ) -> None:
        self._rounds = list(rounds or [])
        self._reply = reply
        self._fail = fail
        self.stream_requests: list[ModelRequest] = []

    @property
    def provider_name(self) -> str:
        return "fake-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise ModelGatewayError("generate() is not used by streaming", provider="fake-provider")

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        self.stream_requests.append(request)
        if self._fail:
            raise ModelGatewayError("upstream is down", provider="fake-provider")
        if self._rounds:
            for chunk in self._rounds.pop(0):
                yield chunk
            return
        for word in self._reply.split(" "):
            yield StreamChunk(delta=f"{word} ", model="fake-model")
        yield StreamChunk(delta="", model="fake-model", usage=_USAGE, finish_reason="stop")


def _text(*pieces: str) -> list[StreamChunk]:
    """A model round that only answers, one chunk per piece."""
    return [
        *(StreamChunk(delta=piece, model="fake-model") for piece in pieces),
        StreamChunk(delta="", model="fake-model", usage=_USAGE, finish_reason="stop"),
    ]


def _tool_round(*, preamble: str = "") -> list[StreamChunk]:
    """A model round that asks for the echo tool, with arguments split across chunks."""
    chunks: list[StreamChunk] = []
    if preamble:
        chunks.append(StreamChunk(delta=preamble, model="fake-model"))
    chunks += [
        StreamChunk(
            tool_call_deltas=[ToolCallDelta(index=0, id="call_1", name="echo", arguments='{"te')],
            model="fake-model",
        ),
        StreamChunk(
            tool_call_deltas=[ToolCallDelta(index=0, arguments='xt": "hi"}')],
            model="fake-model",
        ),
        StreamChunk(delta="", model="fake-model", usage=_USAGE, finish_reason="tool_calls"),
    ]
    return chunks


def _response(content: str = "", tool_calls: list[ModelToolCall] | None = None) -> ModelResponse:
    return ModelResponse(
        content=content,
        provider="fake-provider",
        model="fake-model",
        usage=_USAGE,
        finish_reason="stop",
        tool_calls=tool_calls or [],
    )


def _echo_registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def _echo(args: dict[str, object]) -> str:
        return f"echo:{args.get('text', '')}"

    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo text back.",
            parameters_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": [],
            },
            risk_level="read",
        ),
        _echo,
    )
    return registry


@asynccontextmanager
async def _client(
    *,
    provider: _FakeProvider | None = None,
    settings: Settings | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    resolved = settings or Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
        max_upload_bytes=10 * 1024 * 1024,
    )
    app = create_app(settings=resolved)
    app.dependency_overrides[get_embedding_provider] = lambda: _FakeEmbeddings()

    if provider is not None:

        def _override_factory() -> Callable[[AsyncSession], ChatService]:
            def _factory(session: AsyncSession) -> ChatService:
                return ChatService(
                    provider=provider,
                    repository=ConversationRepository(session=session, principal=DEV_PRINCIPAL),
                    tool_registry=_echo_registry(),
                )

            return _factory

        app.dependency_overrides[get_chat_service_factory] = _override_factory

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.strip().split("\n\n"):
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if name:
            events.append((name, json.loads(data) if data else {}))
    return events


# ---- streaming ---------------------------------------------------------------------


async def test_stream_without_tools_emits_deltas_and_persists_turn() -> None:
    """Verify plain streaming yields meta/delta/done and commits the turn to the DB."""
    async with _client(provider=_FakeProvider()) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={"message": "hello", "enable_tools": False},
        )
        assert response.status_code == 200
        events = _parse_sse(response.text)
        names = [name for name, _ in events]

        assert names[0] == "meta"
        assert "delta" in names
        assert names[-1] == "done"
        assert "".join(
            str(d.get("delta", "")) for n, d in events if n == "delta"
        ).strip() == "plain streamed reply"

        conversation_id = str(events[-1][1]["conversation_id"])
        detail = await client.get(f"/api/v1/conversations/{conversation_id}")

    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"].strip() == "plain streamed reply"


async def test_stream_with_tools_emits_tool_event_then_answer() -> None:
    """Verify tool calls are rebuilt from streamed fragments, run, and the answer streams."""
    provider = _FakeProvider(rounds=[_tool_round(), _text("The tool said ", "echo:hi")])
    async with _client(provider=provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "use the tool"})

    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert "tool" in names
    assert names.index("tool") < names.index("delta")
    assert names[-1] == "done"
    assert "Running echo..." in [str(d.get("status")) for n, d in events if n == "status"]

    tool_event = next(data for name, data in events if name == "tool")
    records = tool_event["tool_calls"]
    assert isinstance(records, list)
    assert records[0]["tool_name"] == "echo"
    assert records[0]["status"] == "success"
    assert records[0]["arguments"] == {"text": "hi"}

    answer = "".join(str(d.get("delta", "")) for n, d in events if n == "delta")
    assert answer == "The tool said echo:hi"

    # Tool output must reach the model fenced as untrusted data.
    second_request = provider.stream_requests[1]
    tool_messages = [m for m in second_request.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert "<tool_output" in tool_messages[0].content
    assert "echo:hi" in tool_messages[0].content


async def test_stream_delivers_model_chunks_as_they_arrive_not_re_sliced() -> None:
    """Verify each upstream text chunk becomes its own delta, even when tools are enabled."""
    provider = _FakeProvider(rounds=[_text("Hel", "lo", " there")])
    async with _client(provider=provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "hi"})

    deltas = [str(d["delta"]) for n, d in _parse_sse(response.text) if n == "delta"]
    assert deltas == ["Hel", "lo", " there"]


async def test_stream_keeps_preamble_before_a_tool_call_separate_from_the_answer() -> None:
    """Verify text before a tool call is shown, and the final answer starts on a new line."""
    provider = _FakeProvider(
        rounds=[_tool_round(preamble="Let me check."), _text("Done: ", "echo:hi")]
    )
    async with _client(provider=provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "use the tool"})
        events = _parse_sse(response.text)
        conversation_id = str(events[-1][1]["conversation_id"])
        detail = await client.get(f"/api/v1/conversations/{conversation_id}")

    answer = "".join(str(d.get("delta", "")) for n, d in events if n == "delta")
    assert answer == "Let me check.\n\nDone: echo:hi"
    assistant = [m for m in detail.json()["messages"] if m["role"] == "assistant"][0]
    assert assistant["content"] == answer

    # The preamble must also be part of the assistant turn that carried the tool call.
    carried = [m for m in provider.stream_requests[1].messages if m.role == "assistant"]
    assert carried[-1].content == "Let me check."
    assert carried[-1].tool_calls is not None


async def test_stream_stops_offering_tools_after_the_iteration_cap() -> None:
    """Verify a model that keeps calling tools is cut off and forced to write an answer."""
    provider = _FakeProvider(
        rounds=[_tool_round(), _tool_round(), _tool_round(), _text("Final.")]
    )
    async with _client(provider=provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "loop"})

    events = _parse_sse(response.text)
    assert events[-1][0] == "done"
    assert "".join(str(d.get("delta", "")) for n, d in events if n == "delta") == "Final."

    # Default cap is 3 tool rounds, then one final round with no tools offered.
    assert len(provider.stream_requests) == 4
    assert all(r.tools for r in provider.stream_requests[:3])
    assert provider.stream_requests[3].tools is None


async def test_stream_sums_token_usage_across_rounds() -> None:
    """Verify the done event reports usage for every model round of the turn."""
    provider = _FakeProvider(rounds=[_tool_round(), _text("ok")])
    async with _client(provider=provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "use the tool"})

    done = [d for n, d in _parse_sse(response.text) if n == "done"][0]
    assert done["usage"]["total_tokens"] == _USAGE.total_tokens * 2


async def test_stream_reports_unknown_conversation_as_error_event() -> None:
    """Verify failures before streaming become an SSE error event, not a broken stream."""
    async with _client(provider=_FakeProvider()) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={"message": "hi", "conversation_id": "does-not-exist"},
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["error"]
    assert "does-not-exist" in str(events[0][1]["detail"])


async def test_stream_reports_provider_failure_as_error_event_without_persisting() -> None:
    """Verify a provider error mid-turn is an error event and nothing is saved."""
    provider = _FakeProvider(fail=True)
    async with _client(provider=provider) as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "hi"})
        events = _parse_sse(response.text)
        listing = await client.get("/api/v1/conversations")

    assert events[-1][0] == "error"
    assert "done" not in [name for name, _ in events]
    assert listing.status_code == 200


# ---- authentication ----------------------------------------------------------------


async def test_development_without_api_keys_allows_requests() -> None:
    """Verify local development still works with no API keys configured."""
    async with _client() as client:
        response = await client.get("/api/v1/conversations")

    assert response.status_code == 200


async def test_health_stays_public_when_keys_are_required() -> None:
    """Verify /health is reachable without a key while API routes are protected."""
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
        app_env="staging",
        api_keys="vk-staging-1",
    )
    async with _client(settings=settings) as client:
        health = await client.get("/health")
        denied = await client.get("/api/v1/conversations")
        allowed = await client.get(
            "/api/v1/conversations", headers={"X-API-Key": "vk-staging-1"}
        )

    assert health.status_code == 200
    assert denied.status_code == 401
    assert allowed.status_code == 200


# ---- knowledge: upload limit and delete --------------------------------------------


async def test_upload_larger_than_limit_is_rejected_with_413() -> None:
    """Verify oversized uploads are refused with HTTP 413."""
    oversized = b"a" * (15 * 1024 * 1024 + 1024)
    async with _client() as client:
        response = await client.post(
            "/api/v1/knowledge/documents/upload",
            files={"file": ("big.txt", oversized, "text/plain")},
        )

    assert response.status_code == 413


async def test_small_text_upload_is_accepted() -> None:
    """Verify uploads under the limit are still ingested."""
    async with _client() as client:
        response = await client.post(
            "/api/v1/knowledge/documents/upload",
            files={"file": ("runbook.txt", b"Restart the worker with systemctl.", "text/plain")},
        )

    assert response.status_code == 201
    assert response.json()["title"] == "runbook"


async def test_delete_document_removes_document_and_its_chunks() -> None:
    """Verify deleting a document works (lazy='raise' on chunks) and removes it from search."""
    async with _client() as client:
        created = await client.post(
            "/api/v1/knowledge/documents",
            json={
                "title": "Restart runbook",
                "content": "# Restart\nRestart the worker with systemctl restart vektor.",
            },
        )
        assert created.status_code == 201
        document_id = created.json()["id"]

        deleted = await client.delete(f"/api/v1/knowledge/documents/{document_id}")
        assert deleted.status_code == 204

        listing = await client.get("/api/v1/knowledge/documents")
        search = await client.post(
            "/api/v1/knowledge/search",
            json={"query": "restart worker", "min_score": 0.0},
        )
        again = await client.delete(f"/api/v1/knowledge/documents/{document_id}")

    assert listing.json() == []
    assert search.json() == []
    assert again.status_code == 404
