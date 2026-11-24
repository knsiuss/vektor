from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from api.main import create_app
from core.config.settings import Settings


@asynccontextmanager
async def _secured_client(
    *,
    api_keys: str = "vk-prod-secret-1,vk-prod-secret-2",
    rate_limit_per_minute: int = 3,
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
        api_keys=api_keys,
        rate_limit_per_minute=rate_limit_per_minute,
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


async def test_api_key_authentication_protects_api_routes_but_allows_health() -> None:
    """Verify /health stays public while /api/v1/* requires a valid configured API key."""
    async with _secured_client() as client:
        health = await client.get("/health")
        assert health.status_code == 200

        no_key = await client.get("/api/v1/conversations")
        assert no_key.status_code == 401

        wrong_key = await client.get(
            "/api/v1/conversations",
            headers={"X-API-Key": "wrong-key"},
        )
        assert wrong_key.status_code == 401

        valid_header = await client.get(
            "/api/v1/conversations",
            headers={"X-API-Key": "vk-prod-secret-1"},
        )
        assert valid_header.status_code == 200

        valid_bearer = await client.get(
            "/api/v1/conversations",
            headers={"Authorization": "Bearer vk-prod-secret-2"},
        )
        assert valid_bearer.status_code == 200


async def test_sliding_window_rate_limiter_enforces_quota_per_minute() -> None:
    """Verify requests exceeding rate_limit_per_minute receive HTTP 429."""
    async with _secured_client(rate_limit_per_minute=2) as client:
        headers = {"X-API-Key": "vk-prod-secret-1"}

        r1 = await client.get("/api/v1/conversations", headers=headers)
        r2 = await client.get("/api/v1/conversations", headers=headers)
        r3 = await client.get("/api/v1/conversations", headers=headers)

    assert r1.status_code == 200
    assert r1.headers["X-RateLimit-Remaining"] == "1"
    assert r2.status_code == 200
    assert r2.headers["X-RateLimit-Remaining"] == "0"
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers
