import httpx

from api.main import create_app


async def test_health_check_returns_ok() -> None:
    """Verify that GET /health returns HTTP 200 and expected liveness payload."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
