from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdwon lifecycle events"""
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the Vektor FastAPI application instance."""
    resolved_settings = settings or get_settings()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=resolved_settings.app_description,
        debug=resolved_settings.debug,
        docs_url="/docs" if resolved_settings.docs_enabled else None,
        redoc_url="/redoc" if resolved_settings.docs_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.docs_enabled else None,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings

    @application.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        """Return basic service liveness status."""
        return {"status": "ok"}

    return application


app = create_app()
