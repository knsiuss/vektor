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
from modules.usage.models import ToolUsageEvent


class _FakeProvider:
    @property
    def provider_name(self) -> str:
        return "fake-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="ok",
            provider=self.provider_name,
            model="fake-model",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
        )


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(app: FastAPI, *, tenant: str, user: str, roles: str = "member") -> str:
    raw = f"vk_tools_{tenant}_{user}"
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


async def _record(
    app: FastAPI,
    *,
    tenant: str,
    user: str,
    tool: str,
    status: str,
    duration_ms: int,
) -> None:
    async with app.state.session_factory() as session:
        session.add(
            ToolUsageEvent(
                tenant_id=tenant,
                user_id=user,
                tool_name=tool,
                status=status,
                duration_ms=duration_ms,
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
            "bob": await _make_key(app, tenant="acme", user="bob"),
        }


async def test_tool_report_ranks_by_calls_and_computes_shares() -> None:
    """Verify ordering, share, success rate and average duration per tool."""
    async with _app() as (client, app, keys):
        base = {"tenant": "acme", "user": "alice"}
        await _record(app, **base, tool="search_knowledge_base", status="success", duration_ms=10)
        await _record(app, **base, tool="search_knowledge_base", status="success", duration_ms=30)
        await _record(app, **base, tool="get_system_health", status="error", duration_ms=5)
        # Another user's calls must not appear in the caller's report.
        await _record(
            app,
            tenant="acme",
            user="bob",
            tool="search_knowledge_base",
            status="success",
            duration_ms=1,
        )

        report = await client.get("/api/v1/usage/tools", headers=_h(keys["alice"]))

    body = report.json()
    assert report.status_code == 200
    assert body["total_calls"] == 3
    assert [tool["tool_name"] for tool in body["tools"]] == [
        "search_knowledge_base",
        "get_system_health",
    ]
    first, second = body["tools"]
    assert first["calls"] == 2
    assert first["share"] == 0.6667
    assert first["success_rate"] == 1.0
    assert first["avg_duration_ms"] == 20.0
    assert second["success_rate"] == 0.0


async def test_tool_report_is_empty_without_calls() -> None:
    """Verify a caller with no tool usage gets an empty report rather than an error."""
    async with _app() as (client, _app_, keys):
        report = await client.get("/api/v1/usage/tools", headers=_h(keys["alice"]))

    assert report.status_code == 200
    assert report.json() == {"days": 30, "total_calls": 0, "tools": []}


async def test_tool_report_rejects_out_of_range_days() -> None:
    """Verify the days and limit parameters are bounded."""
    async with _app() as (client, _app_, keys):
        zero = await client.get("/api/v1/usage/tools?days=0", headers=_h(keys["alice"]))
        huge = await client.get("/api/v1/usage/tools?limit=99", headers=_h(keys["alice"]))

    assert zero.status_code == 422
    assert huge.status_code == 422
