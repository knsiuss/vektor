from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from api.main import create_app
from core.config.settings import Settings


@asynccontextmanager
async def _client() -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def test_prompt_list_starts_with_the_shipped_default() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/prompts")

    assert response.status_code == 200
    items = response.json()
    assert [item["key"] for item in items] == ["system"]
    assert items[0]["is_custom"] is False
    assert items[0]["content"] == items[0]["default_content"]
    assert "Vektor" in items[0]["content"]


async def test_prompt_override_is_saved_and_reset() -> None:
    async with _client() as client:
        saved = await client.put(
            "/api/v1/prompts/system",
            json={"content": "You are a terse operations assistant."},
        )
        listed = await client.get("/api/v1/prompts")
        reset = await client.delete("/api/v1/prompts/system")
        after = await client.get("/api/v1/prompts")

    assert saved.status_code == 200
    assert saved.json()["is_custom"] is True
    assert listed.json()[0]["content"] == "You are a terse operations assistant."
    assert reset.status_code == 204
    assert after.json()[0]["is_custom"] is False


async def test_unknown_prompt_key_is_rejected() -> None:
    async with _client() as client:
        response = await client.put("/api/v1/prompts/nope", json={"content": "x"})

    assert response.status_code == 404


async def test_empty_prompt_is_rejected() -> None:
    async with _client() as client:
        response = await client.put("/api/v1/prompts/system", json={"content": ""})

    assert response.status_code == 422
