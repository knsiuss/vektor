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
from modules.usage.models import KIND_CHAT, UsageEvent


class _FakeProvider:
    @property
    def provider_name(self) -> str:
        return "fake-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="ok",
            provider=self.provider_name,
            model="fake-model",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            finish_reason="stop",
        )


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(app: FastAPI, *, tenant: str, user: str, roles: str = "member") -> str:
    raw = f"vk_budget_{tenant}_{user}"
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


async def _spend_tokens(app: FastAPI, *, tenant: str, tokens: int) -> None:
    """Insert a usage event directly so the budget math does not need a real model call."""
    async with app.state.session_factory() as session:
        session.add(
            UsageEvent(
                tenant_id=tenant,
                user_id="alice",
                kind=KIND_CHAT,
                provider="fake-provider",
                model="fake-model",
                prompt_tokens=tokens,
                completion_tokens=0,
                total_tokens=tokens,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


@asynccontextmanager
async def _app() -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI, dict[str, str]]]:
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
        yield client, app, {
            "alice": await _make_key(app, tenant="acme", user="alice"),
            "carol": await _make_key(app, tenant="acme", user="carol", roles="admin"),
            "dave": await _make_key(app, tenant="globex", user="dave", roles="admin"),
        }


async def test_budget_is_unlimited_until_an_admin_sets_a_ceiling() -> None:
    """Verify a tenant without a budget row reports unlimited and chat keeps working."""
    async with _app() as (client, app, keys):
        status = await client.get("/api/v1/usage/budget", headers=_h(keys["alice"]))
        chat = await client.post(
            "/api/v1/chat", json={"message": "hello"}, headers=_h(keys["alice"])
        )

    assert status.status_code == 200
    assert status.json()["state"] == "unlimited"
    assert status.json()["limit_tokens"] is None
    assert chat.status_code == 200


async def test_admin_can_set_the_ceiling_and_members_cannot() -> None:
    """Verify only admins may change the ceiling, and the change is visible to the tenant."""
    async with _app() as (client, _app_, keys):
        denied = await client.put(
            "/api/v1/admin/budget",
            json={"monthly_token_limit": 1000},
            headers=_h(keys["alice"]),
        )
        allowed = await client.put(
            "/api/v1/admin/budget",
            json={"monthly_token_limit": 1000, "warn_ratio": 0.75},
            headers=_h(keys["carol"]),
        )
        seen = await client.get("/api/v1/usage/budget", headers=_h(keys["alice"]))

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["limit_tokens"] == 1000
    assert seen.json()["limit_tokens"] == 1000
    assert seen.json()["state"] == "ok"


async def test_exhausted_budget_rejects_chat_with_429() -> None:
    """Verify a tenant that spent its whole ceiling cannot start another turn."""
    async with _app() as (client, app, keys):
        await client.put(
            "/api/v1/admin/budget",
            json={"monthly_token_limit": 10},
            headers=_h(keys["carol"]),
        )
        await _spend_tokens(app, tenant="acme", tokens=10)

        blocked = await client.post(
            "/api/v1/chat", json={"message": "hello"}, headers=_h(keys["alice"])
        )
        status = await client.get("/api/v1/usage/budget", headers=_h(keys["alice"]))

    assert blocked.status_code == 429
    assert "budget" in blocked.json()["detail"].lower()
    assert status.json()["state"] == "exhausted"


async def test_warning_state_appears_before_the_ceiling_is_hit() -> None:
    """Verify spend above the warn ratio is flagged while chat still works."""
    async with _app() as (client, app, keys):
        await client.put(
            "/api/v1/admin/budget",
            json={"monthly_token_limit": 100, "warn_ratio": 0.8},
            headers=_h(keys["carol"]),
        )
        await _spend_tokens(app, tenant="acme", tokens=85)

        status = await client.get("/api/v1/usage/budget", headers=_h(keys["alice"]))
        chat = await client.post(
            "/api/v1/chat", json={"message": "hello"}, headers=_h(keys["alice"])
        )

    assert status.json()["state"] == "warning"
    assert chat.status_code == 200


async def test_budget_is_scoped_to_the_tenant() -> None:
    """Verify another tenant's spend and ceiling never leak across."""
    async with _app() as (client, app, keys):
        await client.put(
            "/api/v1/admin/budget",
            json={"monthly_token_limit": 5},
            headers=_h(keys["carol"]),
        )
        await _spend_tokens(app, tenant="acme", tokens=5)

        other = await client.get("/api/v1/usage/budget", headers=_h(keys["dave"]))
        other_chat = await client.post(
            "/api/v1/chat", json={"message": "hello"}, headers=_h(keys["dave"])
        )

    assert other.json()["state"] == "unlimited"
    assert other.json()["used_tokens"] == 0
    assert other_chat.status_code == 200
