import httpx
import pytest
from pydantic import ValidationError

from api.main import create_app
from core.config.settings import Settings


def test_settings_default_values() -> None:
    """Verify secure default settings when no overrides are provided."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.app_name == "Vektor"
    assert settings.app_env == "development"
    assert settings.debug is False
    assert settings.is_production is False
    assert settings.docs_enabled is True


def test_settings_rejects_invalid_environment() -> None:
    """Verify Settings fails closed when given an unsupported environment value."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="invalid_env")  # type: ignore[call-arg, arg-type]


async def test_docs_disabled_in_production() -> None:
    """Verify OpenAPI docs and schema return 404 when running in production."""
    prod_settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="production",
        api_keys="vk-prod-secret-1",
    )
    app = create_app(settings=prod_settings)
    headers = {"X-API-Key": "vk-prod-secret-1"}

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        docs_response = await client.get("/docs", headers=headers)
        openapi_response = await client.get("/openapi.json", headers=headers)

    assert prod_settings.is_production is True
    assert prod_settings.docs_enabled is False
    assert docs_response.status_code == 404
    assert openapi_response.status_code == 404
