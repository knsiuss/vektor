import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    get_chat_service,
    get_db_session,
    get_embedding_provider,
    get_principal,
    get_usage_recorder,
)
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import Principal, hash_api_key
from modules.identity.repository import ApiKeyRepository
from modules.model_gateway.embeddings import OpenAICompatibleEmbeddingProvider
from modules.model_gateway.schemas import ModelRequest, ModelResponse, StreamChunk, TokenUsage
from modules.usage.metered import MeteredProvider
from modules.usage.models import KIND_CHAT, UsageEvent
from modules.usage.recorder import UsageRecorder


class _FakeProvider:
    @property
    def provider_name(self) -> str:
        return "fake-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="ok",
            provider="fake-provider",
            model="fake-model",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            finish_reason="stop",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="hi ", model="fake-model")
        yield StreamChunk(
            delta="",
            model="fake-model",
            usage=TokenUsage(prompt_tokens=4, completion_tokens=6, total_tokens=10),
            finish_reason="stop",
        )


def _embedding_transport(calls: list[int]) -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(len(body["input"]))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [1.0, 0.0, 0.0]} for i in range(len(body["input"]))
                ],
                "usage": {"prompt_tokens": 40, "total_tokens": 40},
            },
        )

    return httpx.MockTransport(_handler)


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(app: FastAPI, *, tenant: str, user: str, roles: str = "member") -> str:
    raw = f"vk_use_{tenant}_{user}"
    async with app.state.session_factory() as session:
        await ApiKeyRepository(session).create(
            tenant_id=tenant,
            user_id=user,
            key_hash=hash_api_key(raw),
            roles=roles,
            label=None,
            expires_at=None,
        )
        await session.commit()
    return raw


@asynccontextmanager
async def _app() -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI, dict[str, str]]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)
    embed_calls: list[int] = []
    app.state.embed_calls = embed_calls

    def _embeddings(
        recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
    ) -> OpenAICompatibleEmbeddingProvider:
        return OpenAICompatibleEmbeddingProvider(
            api_key=SecretStr("k"),
            base_url="https://example.test/v1",
            embedding_model="fake-embed",
            client=httpx.AsyncClient(transport=_embedding_transport(embed_calls)),
            on_usage=recorder.hook(kind="embedding", provider="fake-provider"),
        )

    def _chat(
        session: Annotated[AsyncSession, Depends(get_db_session)],
        principal: Annotated[Principal, Depends(get_principal)],
        recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
    ) -> ChatService:
        return ChatService(
            provider=MeteredProvider(_FakeProvider(), recorder, kind=KIND_CHAT),
            repository=ConversationRepository(session=session, principal=principal),
        )

    app.dependency_overrides[get_embedding_provider] = _embeddings
    app.dependency_overrides[get_chat_service] = _chat

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        keys = {
            "alice": await _make_key(app, tenant="acme", user="alice"),
            "bob": await _make_key(app, tenant="acme", user="bob"),
            "carol": await _make_key(app, tenant="acme", user="carol", roles="admin"),
            "dave": await _make_key(app, tenant="globex", user="dave", roles="admin"),
        }
        yield client, app, keys


async def test_chat_call_is_metered_per_user() -> None:
    """Verify a chat turn writes one usage event for the caller and nobody else."""
    async with _app() as (client, _app_, keys):
        chat = await client.post("/api/v1/chat", json={"message": "hello"}, headers=_h(keys["alice"]))
        alice = await client.get("/api/v1/usage/breakdown", headers=_h(keys["alice"]))
        bob = await client.get("/api/v1/usage/breakdown", headers=_h(keys["bob"]))

    assert chat.status_code == 200
    body = alice.json()
    assert body["total_calls"] == 1
    assert body["total_tokens"] == 5
    assert [(r["kind"], r["model"]) for r in body["rows"]] == [("chat", "fake-model")]
    assert bob.json()["total_calls"] == 0


async def test_streaming_call_is_metered_after_the_stream_ends() -> None:
    """Verify usage reported in the final stream chunk is persisted."""
    async with _app() as (client, app, keys):
        # Route streaming through the same metered fake provider.
        from api.dependencies import get_chat_service_factory

        def _factory_dep(
            recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
            principal: Annotated[Principal, Depends(get_principal)],
        ):  # type: ignore[no-untyped-def]
            def _factory(session: AsyncSession) -> ChatService:
                return ChatService(
                    provider=MeteredProvider(_FakeProvider(), recorder, kind=KIND_CHAT),
                    repository=ConversationRepository(session=session, principal=principal),
                )

            return _factory

        app.dependency_overrides[get_chat_service_factory] = _factory_dep
        response = await client.post(
            "/api/v1/chat/stream",
            json={"message": "hello", "enable_tools": False},
            headers=_h(keys["alice"]),
        )
        usage = await client.get("/api/v1/usage/breakdown", headers=_h(keys["alice"]))

    assert response.status_code == 200
    assert "event: done" in response.text
    assert usage.json()["total_tokens"] == 10
    assert usage.json()["rows"][0]["kind"] == "chat"


async def test_embedding_calls_are_metered_on_ingest_and_search() -> None:
    """Verify document ingestion and search embeddings are attributed to the calling user."""
    async with _app() as (client, app, keys):
        ingest = await client.post(
            "/api/v1/knowledge/documents",
            json={"title": "Doc", "content": "some searchable content"},
            headers=_h(keys["alice"]),
        )
        search = await client.post(
            "/api/v1/knowledge/search",
            json={"query": "searchable", "min_score": 0.0},
            headers=_h(keys["alice"]),
        )
        usage = await client.get("/api/v1/usage/breakdown", headers=_h(keys["alice"]))

    assert ingest.status_code == 201
    assert search.status_code == 200
    body = usage.json()
    assert [r["kind"] for r in body["rows"]] == ["embedding"]
    assert body["total_calls"] == 2  # one for the document chunks, one for the query
    assert body["prompt_tokens"] == 80


async def test_member_cannot_read_tenant_usage_and_admin_sees_per_user_split() -> None:
    """Verify the tenant breakdown is admin-only, split per user, and tenant-isolated."""
    async with _app() as (client, _app_, keys):
        await client.post("/api/v1/chat", json={"message": "a"}, headers=_h(keys["alice"]))
        await client.post("/api/v1/chat", json={"message": "b"}, headers=_h(keys["alice"]))
        await client.post("/api/v1/chat", json={"message": "c"}, headers=_h(keys["bob"]))

        denied = await client.get("/api/v1/admin/usage/breakdown", headers=_h(keys["bob"]))
        carol = await client.get("/api/v1/admin/usage/breakdown", headers=_h(keys["carol"]))
        carol_total = await client.get(
            "/api/v1/admin/usage/breakdown",
            params={"by_user": "false"},
            headers=_h(keys["carol"]),
        )
        dave = await client.get("/api/v1/admin/usage/breakdown", headers=_h(keys["dave"]))

    assert denied.status_code == 403
    per_user = {r["user_id"]: r["calls"] for r in carol.json()["rows"]}
    assert per_user == {"alice": 2, "bob": 1}
    assert carol_total.json()["total_calls"] == 3
    assert carol_total.json()["rows"][0]["user_id"] is None
    assert dave.json()["total_calls"] == 0


async def test_since_filter_excludes_older_events() -> None:
    """Verify the since/until window limits which events are counted."""
    async with _app() as (client, _app_, keys):
        await client.post("/api/v1/chat", json={"message": "x"}, headers=_h(keys["alice"]))
        future = await client.get(
            "/api/v1/usage/breakdown",
            params={"since": "2999-01-01T00:00:00Z"},
            headers=_h(keys["alice"]),
        )
        past = await client.get(
            "/api/v1/usage/breakdown",
            params={"since": "2000-01-01T00:00:00Z"},
            headers=_h(keys["alice"]),
        )

    assert future.json()["total_calls"] == 0
    assert past.json()["total_calls"] == 1


async def test_failed_flush_never_breaks_the_request() -> None:
    """Verify a metering write failure is swallowed and the buffer is not retained."""

    class _BrokenFactory:
        def __call__(self) -> "_BrokenFactory":
            return self

        async def __aenter__(self) -> None:
            raise RuntimeError("database is down")

        async def __aexit__(self, *_exc: object) -> None:
            return None

    recorder = UsageRecorder(_BrokenFactory(), Principal(user_id="u", tenant_id="t"))  # type: ignore[arg-type]
    recorder.record(kind="chat", provider="p", model="m", total_tokens=3)
    assert recorder.pending_count == 1

    await recorder.flush()  # must not raise

    assert recorder.pending_count == 0


async def test_recorder_clamps_negative_tokens_and_flush_is_idempotent() -> None:
    """Verify bad provider numbers cannot create negative usage and double flush adds nothing."""
    async with _app() as (_client, app, keys):
        recorder = UsageRecorder(
            app.state.session_factory, Principal(user_id="alice", tenant_id="acme")
        )
        recorder.record(kind="chat", provider="p", model="m", prompt_tokens=-5, total_tokens=-5)
        await recorder.flush()
        await recorder.flush()

        async with app.state.session_factory() as session:
            from sqlalchemy import select

            rows = (await session.execute(select(UsageEvent))).scalars().all()

    assert len(rows) == 1
    assert rows[0].prompt_tokens == 0
    assert rows[0].total_tokens == 0
