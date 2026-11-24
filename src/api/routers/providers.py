"""AI provider configuration endpoints.

Authenticated users can store their preferred LLM provider (OpenAI, Anthropic,
Google Gemini, or Custom), the model, an API key, and an optional base URL for
self-hosted endpoints. Raw API keys are never returned by the API.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal, get_settings
from core.config.settings import Settings
from modules.identity.principal import Principal
from modules.providers.catalog import (
    DIRECTORY_VENDOR_PREFIXES,
    ModelCatalog,
    ProviderCatalogError,
    fetch_directory_models,
    fetch_provider_models,
    resolve_base_url,
)
from modules.settings.models import ProviderSetting
from modules.settings.repository import ProviderSettingRepository
from modules.settings.schemas import (
    ConnectionCheckOut,
    ModelCatalogIn,
    ProviderSettingIn,
    ProviderSettingOut,
)

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])

DIRECTORY_MODELS_URL_LABEL = "https://openrouter.ai/models"


def _get_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProviderSettingRepository:
    return ProviderSettingRepository(session=session)


def _to_out(record: ProviderSetting) -> ProviderSettingOut:
    """Map a database row to a client-safe response (never exposes the raw key)."""
    return ProviderSettingOut(
        provider=record.provider,
        model=record.model,
        api_key_configured=record.api_key_hash is not None,
        base_url=record.base_url,
        connection_status=record.connection_status,  # type: ignore[arg-type]
        connection_error=record.connection_error,
        last_checked_at=record.last_checked_at,
        latency_ms=record.latency_ms,
    )


@router.post("/models", response_model=ModelCatalog)
async def list_provider_models(
    payload: ModelCatalogIn,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ModelCatalog:
    """List the models a provider publishes, free ones first, for the settings picker."""
    server_base = resolve_base_url("custom", None, settings.llm_base_url)
    server_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    base_url = resolve_base_url(payload.provider, payload.base_url, settings.llm_base_url)
    # The deployment's key is only reused for its own endpoint, so a draft base URL can
    # never receive it. Everything else needs the caller to supply a key.
    api_key = payload.api_key or (server_key if base_url == server_base else None)
    adapter = payload.provider

    http_client = getattr(request.app.state, "http_client", None)

    # Without a key the provider can only answer 401, so publish its live vendor listing
    # from the public directory instead of a stale hardcoded list.
    if not api_key and not payload.base_url and payload.provider in DIRECTORY_VENDOR_PREFIXES:
        try:
            models = await fetch_directory_models(provider=payload.provider, client=http_client)
        except ProviderCatalogError as exc:
            return ModelCatalog(
                provider=payload.provider,
                models=[],
                error=str(exc),
                endpoint=DIRECTORY_MODELS_URL_LABEL,
            )
        return ModelCatalog(
            provider=payload.provider,
            models=models,
            endpoint=DIRECTORY_MODELS_URL_LABEL,
            source="directory",
        )

    try:
        models = await fetch_provider_models(
            provider=adapter,
            base_url=base_url,
            api_key=api_key,
            client=http_client,
        )
    except ProviderCatalogError as exc:
        return ModelCatalog(provider=payload.provider, models=[], error=str(exc), endpoint=base_url)
    return ModelCatalog(provider=payload.provider, models=models, endpoint=base_url)


@router.get("", response_model=ProviderSettingOut)
async def get_provider_settings(
    principal: Annotated[Principal, Depends(get_principal)],
    repo: Annotated[ProviderSettingRepository, Depends(_get_repository)],
) -> ProviderSettingOut:
    """Return the caller's stored provider settings, or defaults when none exist."""
    record = await repo.get(tenant_id=principal.tenant_id, user_id=principal.user_id)
    if record is None:
        return ProviderSettingOut(
            provider="openai",
            model=None,
            api_key_configured=False,
            base_url=None,
            connection_status="disconnected",
            connection_error=None,
            last_checked_at=None,
            latency_ms=None,
        )
    return _to_out(record)


@router.post("", response_model=ProviderSettingOut, status_code=status.HTTP_201_CREATED)
async def upsert_provider_settings(
    payload: ProviderSettingIn,
    principal: Annotated[Principal, Depends(get_principal)],
    repo: Annotated[ProviderSettingRepository, Depends(_get_repository)],
) -> ProviderSettingOut:
    """Create or update the caller's provider settings."""
    record = await repo.upsert(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        provider=payload.provider,
        model=payload.model,
        api_key=payload.api_key,
        base_url=payload.base_url,
        connection_status="disconnected",
    )
    return _to_out(record)


@router.post("/test", response_model=ConnectionCheckOut)
async def test_provider_connection(
    payload: ProviderSettingIn,
    request: Request,
    repo: Annotated[ProviderSettingRepository, Depends(_get_repository)],
) -> ConnectionCheckOut:
    """Probe the configured provider endpoint without persisting anything.

    Reaches the configured base URL (or the provider default) to verify the key
    works and measures latency. Returns the observed status, model, and latency.
    """
    started = datetime.now(UTC)

    base_url = str(payload.base_url).rstrip("/") if payload.base_url else None
    if not base_url:
        defaults = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "google": "https://generativelanguage.googleapis.com/v1",
            "custom": "",
        }
        base_url = defaults.get(payload.provider, "")

    http_client = getattr(request.app.state, "http_client", None)
    if http_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HTTP client is not available.",
        )

    try:
        response = await http_client.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {payload.api_key}"} if payload.api_key else {},
            timeout=10.0,
        )
        latency_ms = round((datetime.now(UTC) - started).total_seconds() * 1000)
        if response.status_code == 401:
            return ConnectionCheckOut(
                status="disconnected",
                latency_ms=latency_ms,
                model=payload.model,
                error="Invalid API key.",
            )
        if response.status_code >= 400:
            return ConnectionCheckOut(
                status="disconnected",
                latency_ms=latency_ms,
                model=payload.model,
                error=f"Provider returned HTTP {response.status_code}.",
            )
        return ConnectionCheckOut(
            status="connected",
            latency_ms=latency_ms,
            model=payload.model,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 — any connectivity failure is reported honestly
        latency_ms = round((datetime.now(UTC) - started).total_seconds() * 1000)
        return ConnectionCheckOut(
            status="disconnected",
            latency_ms=latency_ms,
            model=payload.model,
            error=str(exc) or "Could not reach the provider.",
        )


@router.delete("/api-key", status_code=status.HTTP_204_NO_CONTENT)
async def clear_provider_api_key(
    principal: Annotated[Principal, Depends(get_principal)],
    repo: Annotated[ProviderSettingRepository, Depends(_get_repository)],
) -> None:
    """Remove the stored API key for the caller."""
    removed = await repo.clear_api_key(tenant_id=principal.tenant_id, user_id=principal.user_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No provider API key configured.",
        )
