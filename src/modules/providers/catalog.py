"""Discover the models a provider exposes, normalized for the settings picker."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
}

# Provider -> OpenRouter vendor prefix. Used only to publish a live model directory when
# the caller has no key for that provider: the ids are current, the pricing is OpenRouter's.
DIRECTORY_VENDOR_PREFIXES: dict[str, str] = {
    "openai": "openai/",
    "anthropic": "anthropic/",
    "google": "google/",
    "mistral": "mistralai/",
    "deepseek": "deepseek/",
    "qwen": "qwen/",
}
DIRECTORY_MODELS_URL = "https://openrouter.ai/api/v1/models"
DIRECTORY_LIMIT = 25
# Routing variants that duplicate a model rather than add a new one.
DIRECTORY_SKIP_SUFFIXES = (":batch", ":online", ":thinking", ":floor")

REQUEST_TIMEOUT_SECONDS = 15.0


class ModelOption(BaseModel):
    """One selectable model id with the metadata providers are willing to publish."""

    id: str
    name: str
    context_length: int | None = None
    prompt_price_per_million: float | None = None
    completion_price_per_million: float | None = None
    # None means the provider did not publish pricing; the UI must not claim it is free.
    is_free: bool | None = None


class ModelCatalog(BaseModel):
    """Result of one provider lookup; `error` is set when discovery failed."""

    provider: str
    models: list[ModelOption]
    error: str | None = None
    endpoint: str = ""
    # "provider" = the endpoint itself answered; "directory" = live OpenRouter listing.
    source: str = "provider"


class ProviderCatalogError(Exception):
    """Raised when a provider cannot list its models."""


def resolve_base_url(provider: str, base_url: str | None, fallback: str) -> str:
    """Prefer the caller's URL, then the provider default, then the server-configured one."""
    if base_url and base_url.strip():
        return base_url.strip().rstrip("/")
    if provider in DEFAULT_BASE_URLS:
        return DEFAULT_BASE_URLS[provider].rstrip("/")
    return fallback.rstrip("/")


async def fetch_provider_models(
    *,
    provider: str,
    base_url: str,
    api_key: str | None,
    client: httpx.AsyncClient | None = None,
) -> list[ModelOption]:
    """List models for an OpenAI-compatible, Anthropic, or Google endpoint."""
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        if provider == "anthropic":
            return await _fetch_anthropic(http, base_url, api_key)
        if provider == "google":
            return await _fetch_google(http, base_url, api_key)
        return await _fetch_openai_compatible(http, base_url, api_key)
    finally:
        if owns_client:
            await http.aclose()


async def _fetch_openai_compatible(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str | None,
) -> list[ModelOption]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    data = await _get_json(client, f"{base_url}/models", headers=headers)
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ProviderCatalogError("Provider returned an unexpected model list.")

    options = [_openai_option(entry) for entry in entries if isinstance(entry, dict)]
    return _sorted_options([option for option in options if option.id])


def _openai_option(entry: dict) -> ModelOption:
    pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
    prompt_price = _per_million(pricing.get("prompt"))
    completion_price = _per_million(pricing.get("completion"))
    model_id = str(entry.get("id", ""))
    is_free = None
    if prompt_price is not None and completion_price is not None:
        is_free = prompt_price == 0 and completion_price == 0
    elif model_id.endswith(":free"):
        is_free = True

    context_length = entry.get("context_length") or entry.get("max_context_length")
    return ModelOption(
        id=model_id,
        name=str(entry.get("name") or model_id),
        context_length=context_length if isinstance(context_length, int) else None,
        prompt_price_per_million=prompt_price,
        completion_price_per_million=completion_price,
        is_free=is_free,
    )


async def _fetch_anthropic(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str | None,
) -> list[ModelOption]:
    headers = {"anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    data = await _get_json(client, f"{base_url}/models", headers=headers)
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ProviderCatalogError("Provider returned an unexpected model list.")

    options = [
        ModelOption(
            id=str(entry.get("id", "")),
            name=str(entry.get("display_name") or entry.get("id", "")),
        )
        for entry in entries
        if isinstance(entry, dict)
    ]
    return _sorted_options([option for option in options if option.id])


async def _fetch_google(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str | None,
) -> list[ModelOption]:
    params = {"key": api_key} if api_key else None
    data = await _get_json(client, f"{base_url}/models", params=params)
    entries = data.get("models") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ProviderCatalogError("Provider returned an unexpected model list.")

    options: list[ModelOption] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).removeprefix("models/")
        if not name:
            continue
        options.append(
            ModelOption(
                id=name,
                name=str(entry.get("displayName") or name),
                context_length=entry.get("inputTokenLimit")
                if isinstance(entry.get("inputTokenLimit"), int)
                else None,
            )
        )
    return _sorted_options(options)


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> dict:
    try:
        response = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise ProviderCatalogError(f"Provider unreachable: {exc.__class__.__name__}.") from exc

    if response.status_code == 401:
        raise ProviderCatalogError("Provider rejected the API key (401).")
    if response.status_code == 429:
        raise ProviderCatalogError("Provider rate limit hit while listing models (429).")
    if response.status_code >= 400:
        raise ProviderCatalogError(f"Provider returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderCatalogError("Provider returned a non-JSON response.") from exc
    if not isinstance(payload, dict):
        raise ProviderCatalogError("Provider returned an unexpected payload.")
    return payload


def _per_million(raw: object) -> float | None:
    """OpenRouter prices are USD per token; convert to USD per million tokens."""
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(value * 1_000_000, 4)


def _sorted_options(options: list[ModelOption]) -> list[ModelOption]:
    """Free models first, then unknown pricing, then paid; alphabetical inside each band."""
    rank = {True: 0, None: 1, False: 2}
    return sorted(options, key=lambda option: (rank[option.is_free], option.id.lower()))


async def fetch_directory_models(
    *,
    provider: str,
    client: httpx.AsyncClient | None = None,
    limit: int = DIRECTORY_LIMIT,
) -> list[ModelOption]:
    """List a vendor's newest models from OpenRouter's public directory, newest first."""
    prefix = DIRECTORY_VENDOR_PREFIXES.get(provider)
    if prefix is None:
        raise ProviderCatalogError(f"No public directory mapping for '{provider}'.")

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        data = await _get_json(http, DIRECTORY_MODELS_URL)
    finally:
        if owns_client:
            await http.aclose()

    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ProviderCatalogError("Model directory returned an unexpected payload.")

    ranked: list[tuple[ModelOption, int]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id", ""))
        if not model_id.startswith(prefix) or model_id.endswith(DIRECTORY_SKIP_SUFFIXES):
            continue
        ranked.append((_openai_option(entry), _as_int(entry.get("created", 0))))

    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return [option for option, _ in ranked][:limit]


def _as_int(raw: object) -> int:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return 0
