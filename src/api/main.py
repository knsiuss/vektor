from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from api.routers import chat
from core.config.settings import Settings, get_settings
from core.database import create_engine, create_session_factory, init_db
from modules.conversations import models as _conversation_models  # noqa: F401


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage shared HTTP client and database engine across startup and shutdown."""
    settings: Settings = application.state.settings
    engine = create_engine(settings.database_url)
    application.state.db_engine = engine
    application.state.session_factory = create_session_factory(engine)
    await init_db(engine)

    try:
        async with httpx.AsyncClient() as http_client:
            application.state.http_client = http_client
            yield
    finally:
        await engine.dispose()


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
    application.include_router(chat.router)

    @application.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        """Return basic service liveness status."""
        return {"status": "ok"}

    return application


app = create_app()
