"""Integration tests for the AI provider settings endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from api.main import create_app
from core.config.settings import Settings


@asynccontextmanager
async def _test_client() -> AsyncIterator[httpx.AsyncClient]:
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


async def test_get_provider_settings_defaults_when_none_configured() -> None:
    """Verify GET /api/v1/providers returns defaults when no row exists."""
    async with _test_client() as client:
        response = await client.get("/api/v1/providers")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["api_key_configured"] is False
    assert body["connection_status"] == "disconnected"


async def test_upsert_and_get_provider_settings() -> None:
    """Verify POST then GET round-trips provider settings."""
    async with _test_client() as client:
        created = await client.post(
            "/api/v1/providers",
            json={
                "provider": "anthropic",
                "model": "claude-3-5-sonnet-20241022",
                "api_key": "sk-ant-test-key",
                "base_url": "https://api.anthropic.com",
            },
        )
        assert created.status_code == 201
        assert created.json()["provider"] == "anthropic"
        assert created.json()["model"] == "claude-3-5-sonnet-20241022"
        assert created.json()["base_url"] == "https://api.anthropic.com"

        fetched = await client.get("/api/v1/providers")
        assert fetched.status_code == 200
        assert fetched.json()["provider"] == "anthropic"
        assert fetched.json()["api_key_configured"] is True
        assert fetched.json()["connection_status"] == "disconnected"


async def test_upsert_updates_existing_settings() -> None:
    """Verify re-POST updates the same row rather than creating a duplicate."""
    async with _test_client() as client:
        await client.post(
            "/api/v1/providers",
            json={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-old"},
        )
        updated = await client.post(
            "/api/v1/providers",
            json={"provider": "google", "model": "gemini-1.5-pro", "api_key": "sk-new"},
        )
        assert updated.status_code == 201
        assert updated.json()["provider"] == "google"
        assert updated.json()["model"] == "gemini-1.5-pro"

        fetched = await client.get("/api/v1/providers")
        assert fetched.json()["provider"] == "google"
        assert fetched.json()["api_key_configured"] is True


async def test_clear_provider_api_key() -> None:
    """Verify DELETE /api/v1/providers/api-key removes the stored key."""
    async with _test_client() as client:
        await client.post(
            "/api/v1/providers",
            json={"provider": "openai", "api_key": "sk-to-be-removed"},
        )
        removed = await client.delete("/api/v1/providers/api-key")
        assert removed.status_code == 204

        fetched = await client.get("/api/v1/providers")
        assert fetched.json()["api_key_configured"] is False
        assert fetched.json()["connection_status"] == "disconnected"


async def test_clear_provider_api_key_returns_404_when_none() -> None:
    """Verify DELETE /api/v1/providers/api-key returns 404 when no key exists."""
    async with _test_client() as client:
        response = await client.delete("/api/v1/providers/api-key")
        assert response.status_code == 404
