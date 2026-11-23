from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """Application runtime configuration loaded and validated from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VEKTOR_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Vektor", min_length=1)
    app_version: str = Field(default="0.1.0", min_length=1)
    app_description: str = Field(
        default="Vektor — A secure, company-aware AI operations platform.",
        min_length=1,
    )
    app_env: Environment = Field(default="development")
    debug: bool = Field(default=False)

    # LLM Provider Configuration (OpenAI-compatible endpoint)
    llm_provider_name: str = Field(default="openai-compatible", min_length=1)
    llm_api_key: SecretStr | None = Field(default=None)
    llm_base_url: str = Field(default="https://api.openai.com/v1", min_length=1)
    llm_default_model: str = Field(default="gpt-4o-mini", min_length=1)
    llm_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)

    llm_embedding_model: str = Field(
        default="openai/text-embedding-3-small",
        min_length=1,
    )
    llm_vision_model: str | None = Field(
        default=None,
        min_length=1,
    )

    # Persistence Configuration
    database_url: str = Field(
        default="sqlite+aiosqlite:///./vektor.db",
        min_length=1,
    )

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.app_env == "production"

    @property
    def docs_enabled(self) -> bool:
        """Disable interactive API docs in production by default."""
        return not self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
