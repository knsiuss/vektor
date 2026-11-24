"""Live model directory used when a provider has no API key to list its own catalogue."""

from __future__ import annotations

import httpx

from modules.providers.catalog import (
    REQUEST_TIMEOUT_SECONDS,
    ModelOption,
    ProviderCatalogError,
    _as_int,
    _get_json,
    _openai_option,
)

# Provider -> OpenRouter vendor prefix. Ids come from the directory, so they stay current
# instead of drifting behind a hardcoded list.
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
