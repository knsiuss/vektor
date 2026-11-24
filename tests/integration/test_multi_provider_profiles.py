from pathlib import Path

import httpx

from api.main import create_app
from core.config.settings import Settings


async def test_multi_provider_profiles_crud_and_secret_redaction(tmp_path: Path) -> None:
    db_file = tmp_path / "profiles.db"
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        llm_embedding_model="local",
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post(
                "/api/v1/providers/profiles",
                json={
                    "label": "OpenRouter Free",
                    "provider": "openrouter",
                    "model": "liquid/lfm-3-1.7b:free",
                    "api_key": "sk-or-secret-1",
                },
            )
            assert r1.status_code == 201
            p1 = r1.json()
            assert p1["api_key_configured"] is True
            assert "sk-or-secret-1" not in r1.text

            r2 = await client.post(
                "/api/v1/providers/profiles",
                json={
                    "label": "OpenAI Work",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "api_key": "sk-openai-secret-2",
                    "is_default": True,
                },
            )
            assert r2.status_code == 201

            listed = await client.get("/api/v1/providers/profiles")
            assert listed.status_code == 200
            items = listed.json()
            assert len(items) == 2
            assert items[0]["label"] == "OpenAI Work"
            assert "sk-openai-secret-2" not in listed.text

            deleted = await client.delete(f"/api/v1/providers/profiles/{p1['id']}")
            assert deleted.status_code == 204
            remaining = (await client.get("/api/v1/providers/profiles")).json()
            assert len(remaining) == 1
