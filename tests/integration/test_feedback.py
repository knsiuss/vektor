from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
            content="The failover runbook says to promote the replica.",
            provider=self.provider_name,
            model="fake-model",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            finish_reason="stop",
        )


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(app: FastAPI, *, tenant: str, user: str, roles: str = "member") -> str:
    raw = f"vk_fb_{tenant}_{user}"
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
async def _app() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)

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
            "alice": await _make_key(app, tenant="acme", user="alice"),
            "bob": await _make_key(app, tenant="acme", user="bob"),
        }


async def _answer_ids(client: httpx.AsyncClient, key: str) -> tuple[str, str]:
    """Create one assistant turn and return (conversation_id, assistant message id)."""
    turn = await client.post(
        "/api/v1/chat", json={"message": "what does the runbook say?"}, headers=_h(key)
    )
    assert turn.status_code == 200
    conversation_id = turn.json()["conversation_id"]

    detail = await client.get(f"/api/v1/conversations/{conversation_id}", headers=_h(key))
    assert detail.status_code == 200
    assistant = [item for item in detail.json()["messages"] if item["role"] == "assistant"]
    assert assistant
    return conversation_id, assistant[-1]["id"]


async def test_feedback_is_recorded_for_the_callers_own_answer() -> None:
    """Verify a thumbs down is stored and returned with the answer it refers to."""
    async with _app() as (client, keys):
        conversation_id, message_id = await _answer_ids(client, keys["alice"])

        created = await client.post(
            "/api/v1/chat/feedback",
            json={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "rating": "down",
                "comment": "It cited a runbook we do not have.",
            },
            headers=_h(keys["alice"]),
        )
        listed = await client.get(
            "/api/v1/usage/feedback", params={"rating": "down"}, headers=_h(keys["alice"])
        )
        other = await client.get("/api/v1/usage/feedback", headers=_h(keys["bob"]))

    assert created.status_code == 201
    assert created.json()["rating"] == "down"

    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["message_id"] == message_id
    assert rows[0]["conversation_title"]
    assert "failover runbook" in rows[0]["excerpt"]
    assert rows[0]["comment"] == "It cited a runbook we do not have."
    assert other.json() == []


async def test_feedback_on_a_foreign_conversation_is_not_found() -> None:
    """Verify another user cannot attach feedback to a message they cannot read."""
    async with _app() as (client, keys):
        conversation_id, message_id = await _answer_ids(client, keys["alice"])

        response = await client.post(
            "/api/v1/chat/feedback",
            json={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "rating": "up",
            },
            headers=_h(keys["bob"]),
        )

    assert response.status_code == 404


async def test_feedback_rating_filter_separates_up_and_down() -> None:
    """Verify the rating filter only returns the rows that match."""
    async with _app() as (client, keys):
        conversation_id, message_id = await _answer_ids(client, keys["alice"])
        for rating in ("up", "down"):
            created = await client.post(
                "/api/v1/chat/feedback",
                json={
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "rating": rating,
                },
                headers=_h(keys["alice"]),
            )
            assert created.status_code == 201

        ups = await client.get(
            "/api/v1/usage/feedback", params={"rating": "up"}, headers=_h(keys["alice"])
        )
        all_rows = await client.get("/api/v1/usage/feedback", headers=_h(keys["alice"]))

    assert [row["rating"] for row in ups.json()] == ["up"]
    assert len(all_rows.json()) == 2
