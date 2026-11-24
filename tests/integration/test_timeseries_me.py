from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session, get_principal
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import Principal, hash_api_key
from modules.identity.repository import ApiKeyRepository
from modules.model_gateway.schemas import ModelRequest, ModelResponse, TokenUsage


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


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(app: FastAPI, *, user: str, roles: str = "member") -> str:
    raw = f"vk_ts_{user}"
    async with app.state.session_factory() as session:
        await ApiKeyRepository(session).create(
            tenant_id="acme",
            user_id=user,
            key_hash=hash_api_key(raw),
            roles=roles,
            label=None,
            expires_at=None,
        )
        await session.commit()
    return raw


@asynccontextmanager
async def _app() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    app = create_app(
        settings=Settings(
            _env_file=None,  # type: ignore[call-arg]
            database_url="sqlite+aiosqlite:///:memory:",
        )
    )

    def _chat(
        session: Annotated[AsyncSession, Depends(get_db_session)],
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> ChatService:
        return ChatService(
            provider=_FakeProvider(),
            repository=ConversationRepository(session=session, principal=principal),
        )

    app.dependency_overrides[get_chat_service] = _chat
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client, {
            "alice": await _make_key(app, user="alice"),
            "bob": await _make_key(app, user="bob"),
            "carol": await _make_key(app, user="carol", roles="admin"),
        }


async def test_me_returns_the_authenticated_identity() -> None:
    """Verify /me reflects the user, tenant and roles behind the presented key."""
    async with _app() as (client, keys):
        member = await client.get("/api/v1/me", headers=_h(keys["alice"]))
        admin = await client.get("/api/v1/me", headers=_h(keys["carol"]))
        anonymous = await client.get("/api/v1/me")

    assert member.json() == {
        "user_id": "alice",
        "tenant_id": "acme",
        "roles": ["member"],
        "is_admin": False,
    }
    assert admin.json()["is_admin"] is True
    assert anonymous.status_code == 401


async def test_timeseries_has_one_point_per_day_and_counts_todays_activity() -> None:
    """Verify daily buckets, today's totals, the empty previous period and per-user scoping."""
    async with _app() as (client, keys):
        await client.post("/api/v1/chat", json={"message": "hello"}, headers=_h(keys["alice"]))
        alice = await client.get("/api/v1/usage/timeseries?days=7", headers=_h(keys["alice"]))
        bob = await client.get("/api/v1/usage/timeseries?days=7", headers=_h(keys["bob"]))

    body = alice.json()
    assert body["days"] == 7
    assert len(body["points"]) == 7
    today = body["points"][-1]
    assert today["date"] == datetime.now(UTC).date().isoformat()
    assert (today["conversations"], today["messages"], today["tokens"]) == (1, 2, 5)
    assert body["current"] == {"conversations": 1, "messages": 2, "tokens": 5}
    assert body["previous"] == {"conversations": 0, "messages": 0, "tokens": 0}
    assert bob.json()["current"] == {"conversations": 0, "messages": 0, "tokens": 0}


async def test_timeseries_rejects_out_of_range_days() -> None:
    """Verify the days parameter is bounded."""
    async with _app() as (client, keys):
        zero = await client.get("/api/v1/usage/timeseries?days=0", headers=_h(keys["alice"]))
        huge = await client.get("/api/v1/usage/timeseries?days=9999", headers=_h(keys["alice"]))

    assert zero.status_code == 422
    assert huge.status_code == 422
