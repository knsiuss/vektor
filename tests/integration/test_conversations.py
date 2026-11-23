from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.model_gateway.schemas import (
    ModelRequest,
    ModelResponse,
    StreamChunk,
    TokenUsage,
)


class _StubProvider:
    @property
    def provider_name(self) -> str:
        return "stub-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="Recorded reply.",
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
async def _test_client() -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)

    def _override_chat(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ChatService:
        return ChatService(
            provider=_StubProvider(),
            repository=ConversationRepository(session=session),
        )

    app.dependency_overrides[get_chat_service] = _override_chat

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def test_list_get_and_delete_conversation_lifecycle() -> None:
    """Verify full lifecycle: create via chat, list, fetch detail, delete, and confirm 404."""
    async with _test_client() as client:
        chat_res = await client.post("/api/v1/chat", json={"message": "Audit server logs"})
        assert chat_res.status_code == 200
        conv_id = chat_res.json()["conversation_id"]

        list_res = await client.get("/api/v1/conversations")
        assert list_res.status_code == 200
        items = list_res.json()
        assert len(items) == 1
        assert items[0]["id"] == conv_id
        assert items[0]["title"] == "Audit server logs"

        detail_res = await client.get(f"/api/v1/conversations/{conv_id}")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert len(detail["messages"]) == 2
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["total_tokens"] == 15

        del_res = await client.delete(f"/api/v1/conversations/{conv_id}")
        assert del_res.status_code == 204

        after_del = await client.get(f"/api/v1/conversations/{conv_id}")
        assert after_del.status_code == 404


async def test_get_and_delete_unknown_conversation_return_404() -> None:
    """Verify unknown conversation IDs return HTTP 404 on GET and DELETE."""
    async with _test_client() as client:
        get_res = await client.get("/api/v1/conversations/missing-id")
        del_res = await client.delete("/api/v1/conversations/missing-id")

    assert get_res.status_code == 404
    assert del_res.status_code == 404
