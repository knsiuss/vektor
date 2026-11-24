from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized, validated application configuration for Vektor."""

    model_config = SettingsConfigDict(
        env_prefix="VEKTOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Vektor"
    app_version: str = "0.1.0"
    app_description: str = "Modular AI Operations platform."
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    docs_enabled: bool = True
    # Create tables on startup (dev/tests). Set False in deployments that use Alembic.
    db_auto_create: bool = True

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    database_url: str = Field(
        default="sqlite+aiosqlite:///./vektor.db",
        min_length=1,
    )
    health_database_timeout_seconds: float = Field(
        default=2.0,
        gt=0.0,
        le=30.0,
    )

    llm_provider_name: str = Field(default="openrouter", min_length=1)
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        min_length=1,
    )
    llm_api_key: SecretStr | None = None
    llm_default_model: str = Field(
        default="openai/gpt-4o-mini",
        min_length=1,
    )
    llm_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    llm_embedding_model: str = Field(
        default="openai/text-embedding-3-small",
        min_length=1,
    )
    llm_embedding_backend: Literal[
        "auto",
        "openai-compatible",
        "voyage",
        "ollama",
        "local-bge",
        "local-hash",
    ] = "auto"
    llm_embedding_provider_name: str | None = None
    llm_embedding_base_url: str | None = None
    llm_embedding_api_key: SecretStr | None = None
    llm_vision_model: str | None = Field(
        default=None,
        min_length=1,
    )
    llm_rewrite_model: str | None = Field(
        default=None,
        min_length=1,
    )
    llm_chat_temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    # OAuth login (Google / GitHub). Empty client id disables that provider.
    public_frontend_url: str = Field(default="http://localhost:3000", min_length=1)
    auth_session_secret: SecretStr | None = None
    auth_session_days: int = Field(default=30, ge=1, le=365)
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: SecretStr | None = None
    oauth_github_client_id: str | None = None
    oauth_github_client_secret: SecretStr | None = None

    api_keys: str = Field(default="")
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)

    agent_max_history_messages: int = Field(default=20, ge=1, le=100)
    agent_max_history_tokens: int = Field(default=3500, ge=256, le=32000)
    agent_max_tool_iterations: int = Field(default=3, ge=1, le=10)
    tool_default_top_k: int = Field(default=4, ge=1, le=10)

    retrieval_min_score_explicit: float = Field(default=0.05, ge=0.0, le=1.0)
    retrieval_min_score_always: float = Field(default=0.25, ge=0.0, le=1.0)
    retrieval_min_score_agentic: float = Field(default=0.28, ge=0.0, le=1.0)
    retrieval_tool_min_score: float = Field(default=0.25, ge=0.0, le=1.0)
    retrieval_max_context_tokens: int = Field(default=2000, ge=256, le=16000)
    retrieval_relative_score_ratio: float = Field(default=0.6, ge=0.0, le=1.0)
    retrieval_stale_days: int = Field(default=180, ge=1, le=3650)
    retrieval_crag_low_confidence: float = Field(default=0.40, ge=0.0, le=1.0)
    retrieval_reranker: Literal["heuristic", "voyage", "local-bge"] = "heuristic"
    retrieval_reranker_model: str | None = None
    retrieval_reranker_api_key: SecretStr | None = None
    knowledge_chunking_strategy: Literal["procedure", "semantic"] = "procedure"

    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    skills_dir: str = "skills"
    sandbox_backend: Literal["disabled", "docker", "ssh"] = "disabled"
    sandbox_docker_image: str = "python:3.12-slim"
    sandbox_workspace_dir: str = "./sandbox_workspace"
    sandbox_ssh_target: str | None = None

    web_tools_enabled: bool = True
    web_search_provider: Literal["duckduckgo", "searxng"] = "searxng"
    # Empty means use the built-in public SearXNG list; set your own for stable results.
    web_searxng_url: str | None = None
    web_max_searches: int = Field(default=3, ge=1, le=10)
    web_max_fetches: int = Field(default=3, ge=1, le=10)
    web_max_results: int = Field(default=5, ge=1, le=10)
    web_fetch_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    web_max_page_chars: int = Field(default=6000, ge=500, le=40000)

    kms_master_key: SecretStr | None = None
    gateway_allow_local_endpoints: bool = False

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.app_env == "production"

    @property
    def resolved_embedding_provider_name(self) -> str:
        """Return dedicated embedding provider name, falling back to llm_provider_name."""
        if self.llm_embedding_provider_name and self.llm_embedding_provider_name.strip():
            return self.llm_embedding_provider_name.strip()
        return self.llm_provider_name

    @property
    def resolved_embedding_base_url(self) -> str:
        """Return dedicated embedding base URL, falling back to llm_base_url."""
        if self.llm_embedding_base_url and self.llm_embedding_base_url.strip():
            return self.llm_embedding_base_url.strip()
        return self.llm_base_url

    @property
    def resolved_embedding_api_key(self) -> SecretStr | None:
        """Return dedicated embedding API key, falling back to llm_api_key when blank."""
        key = self.llm_embedding_api_key
        if key is not None and key.get_secret_value().strip():
            return self.llm_embedding_api_key
        return self.llm_api_key

    def parsed_api_keys(self) -> tuple[str, ...]:
        """Return configured non-empty API keys from comma-separated VEKTOR_API_KEYS."""
        return tuple(item.strip() for item in self.api_keys.split(",") if item.strip())

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        if self.app_env != "development" and not self.parsed_api_keys():
            raise ValueError(
                f"VEKTOR_API_KEYS must be configured when VEKTOR_APP_ENV={self.app_env}."
            )
        if self.is_production:
            if self.debug:
                raise ValueError("VEKTOR_DEBUG must not be enabled when VEKTOR_APP_ENV=production.")
            if not self.parsed_api_keys():
                raise ValueError(
                    "VEKTOR_API_KEYS must be configured when VEKTOR_APP_ENV=production."
                )
            if self.docs_enabled:
                self.docs_enabled = False
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
