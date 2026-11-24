import httpx
import pytest

from api.main import create_app, lifespan
from core.config.settings import Settings


@pytest.mark.asyncio
async def test_widget_crud_cors_and_public_config() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="development",
        database_url="sqlite+aiosqlite:///:memory:",
        db_auto_create=True,
    )
    app = create_app(settings)

    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_res = await client.post(
                "/api/v1/widgets",
                json={
                    "name": "CS Toko",
                    "allowed_domains": ["tokoku.com"],
                    "welcome_message": "Halo!",
                },
            )
            assert create_res.status_code == 201
            widget = create_res.json()
            public_key = widget["public_key"]
            assert public_key.startswith("vwk_")

            preflight = await client.options(
                f"/api/v1/public/widgets/{public_key}/config",
                headers={"Origin": "https://tokoku.com"},
            )
            assert preflight.status_code == 204
            assert preflight.headers.get("access-control-allow-origin") == "https://tokoku.com"

            blocked = await client.get(
                f"/api/v1/public/widgets/{public_key}/config",
                headers={"Origin": "https://attacker.com"},
            )
            assert blocked.status_code == 403

            allowed = await client.get(
                f"/api/v1/public/widgets/{public_key}/config",
                headers={"Origin": "https://tokoku.com"},
            )
            assert allowed.status_code == 200
            assert allowed.json()["name"] == "CS Toko"

            del_res = await client.delete(f"/api/v1/widgets/{widget['id']}")
            assert del_res.status_code == 204
