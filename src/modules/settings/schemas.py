"""Pydantic schemas for AI provider settings API requests and responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal[
    "openai", "anthropic", "google", "openrouter", "mistral", "deepseek", "qwen", "custom"
]
ConnectionStatus = Literal["connected", "disconnected", "checking"]


class ProviderSettingIn(BaseModel):
    """Incoming provider configuration from the frontend."""

    provider: ProviderName = Field(default="openai")
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None)
    base_url: str | None = Field(default=None, max_length=512)


class ProviderSettingOut(BaseModel):
    """Serialized provider settings, safe to return to the client (no raw keys)."""

    provider: str
    model: str | None
    api_key_configured: bool
    base_url: str | None
    connection_status: ConnectionStatus
    connection_error: str | None
    last_checked_at: datetime | None
    latency_ms: int | None

    model_config = ConfigDict(from_attributes=True)


class ConnectionCheckOut(BaseModel):
    """Result of testing a provider connection."""

    status: ConnectionStatus
    latency_ms: int | None
    model: str | None
    error: str | None


class ModelCatalogIn(BaseModel):
    """Draft provider values used to list models before they are saved."""

    provider: ProviderName = Field(default="openai")
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None)
