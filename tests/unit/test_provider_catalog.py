from types import SimpleNamespace

import httpx
import pytest

from api.routers.providers import list_provider_models
from core.config.settings import Settings
from modules.providers.catalog import (
    ProviderCatalogError,
    fetch_provider_models,
    resolve_base_url,
)
from modules.settings.schemas import ModelCatalogIn


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_openai_compatible_listing_marks_free_models_and_sorts_them_first() -> None:
    """Zero pricing means free; free entries must lead the list for the free-tier default."""
    payload = {
        "data": [
            {"id": "paid-model", "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
            {"id": "free-model", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "unknown-model"},
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with _client(transport) as client:
        models = await fetch_provider_models(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key",
            client=client,
        )

    assert [model.id for model in models] == ["free-model", "unknown-model", "paid-model"]
    assert models[0].is_free is True
    assert models[1].is_free is None
    assert models[2].prompt_price_per_million == 3.0
    assert models[2].completion_price_per_million == 15.0


async def test_free_suffix_marks_a_model_free_when_pricing_is_absent() -> None:
    """Providers that omit pricing but suffix `:free` still get the free badge."""
    payload = {"data": [{"id": "vendor/thing:free"}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with _client(transport) as client:
        models = await fetch_provider_models(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=None,
            client=client,
        )

    assert models[0].is_free is True


async def test_anthropic_listing_uses_its_own_headers_and_shape() -> None:
    """Anthropic needs x-api-key + version header and returns display_name."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(
            200,
            json={"data": [{"id": "claude-x", "display_name": "Claude X"}]},
        )

    async with _client(httpx.MockTransport(handler)) as client:
        models = await fetch_provider_models(
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key="sk-ant",
            client=client,
        )

    assert models[0].name == "Claude X"
    assert seen["x-api-key"] == "sk-ant"
    assert seen["anthropic-version"] == "2023-06-01"


async def test_google_listing_strips_the_models_prefix() -> None:
    """Gemini model ids arrive as `models/<id>` and must be selectable as `<id>`."""
    payload = {"models": [{"name": "models/gemini-2.0-flash", "displayName": "Gemini 2.0 Flash"}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with _client(transport) as client:
        models = await fetch_provider_models(
            provider="google",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="key",
            client=client,
        )

    assert models[0].id == "gemini-2.0-flash"


async def test_unauthorized_listing_raises_a_readable_error() -> None:
    """A revoked key must surface as a catalog error, not an empty success."""
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={}))

    with pytest.raises(ProviderCatalogError, match="401"):
        async with _client(transport) as client:
            await fetch_provider_models(
                provider="openai",
                base_url="https://api.openai.com/v1",
                api_key="bad",
                client=client,
            )


async def test_endpoint_returns_error_instead_of_failing_when_provider_is_down() -> None:
    """The settings picker keeps working: it gets an error string and an empty list."""
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={}))
    http_client = httpx.AsyncClient(transport=transport)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http_client=http_client)))
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")

    catalog = await list_provider_models(
        ModelCatalogIn(provider="openrouter", base_url="https://openrouter.ai/api/v1"),
        request,
        settings,
    )

    await http_client.aclose()
    assert catalog.models == []
    assert catalog.error and "500" in catalog.error


async def test_server_key_is_not_sent_to_a_draft_base_url() -> None:
    """A user-supplied endpoint must never receive the deployment's API key."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"data": []})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http_client=http_client)))
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="server-secret",
        llm_base_url="https://openrouter.ai/api/v1",
    )

    await list_provider_models(
        ModelCatalogIn(provider="custom", base_url="https://evil.example.com/v1"),
        request,
        settings,
    )

    await http_client.aclose()
    assert captured["auth"] == ""


async def test_provider_selection_decides_which_endpoint_is_listed() -> None:
    """With a key for the picked provider, only that provider's endpoint is called."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"data": [{"id": "gemini-2.0-flash"}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http_client=http_client)))
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="server-secret",
        llm_base_url="https://openrouter.ai/api/v1",
    )

    catalog = await list_provider_models(
        ModelCatalogIn(provider="google", api_key="google-key"),
        request,
        settings,
    )

    await http_client.aclose()
    assert captured["url"].startswith("https://generativelanguage.googleapis.com/v1beta/models")
    assert "key=google-key" in captured["url"]
    assert catalog.source == "provider"
    assert catalog.endpoint.startswith("https://generativelanguage.googleapis.com")


async def test_missing_key_falls_back_to_the_live_directory() -> None:
    """No key -> newest vendor models from the public directory, never a stale hardcoded list."""
    payload = {
        "data": [
            {"id": "anthropic/claude-sonnet-5.5", "created": "1790000000"},
            {"id": "anthropic/claude-fable-5.2", "created": "1794000000"},
            {"id": "anthropic/claude-fable-5.2:batch", "created": "1794000001"},
            {"id": "google/gemini-4-neon", "created": "1795000000"},
        ]
    }
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http_client=http_client)))
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        llm_base_url="https://openrouter.ai/api/v1",
    )

    catalog = await list_provider_models(ModelCatalogIn(provider="anthropic"), request, settings)

    await http_client.aclose()
    assert catalog.source == "directory"
    # Newest first, other vendors and batch routing variants excluded.
    assert [model.id for model in catalog.models] == [
        "anthropic/claude-fable-5.2",
        "anthropic/claude-sonnet-5.5",
    ]


def test_resolve_base_url_priority() -> None:
    """Explicit URL wins, then the provider default, then the server fallback."""
    assert resolve_base_url("custom", "https://x/v1/", "https://fallback") == "https://x/v1"
    assert resolve_base_url("openai", None, "https://fallback") == "https://api.openai.com/v1"
    assert resolve_base_url("custom", None, "https://fallback/") == "https://fallback"
