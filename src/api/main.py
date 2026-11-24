from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from starlette.responses import StreamingResponse

from api.auth import resolve_principal
from api.middleware import request_context_middleware
from api.routers import (
    admin,
    chat,
    conversations,
    gateway,
    keys,
    knowledge,
    mcp,
    me,
    providers,
    usage,
    workflows,
)
from api.security import (
    SlidingWindowRateLimiter,
    build_rate_limited_response,
    build_unauthorized_response,
    extract_presented_api_key,
)
from core.config.settings import Settings, get_settings
from core.database import create_engine, create_session_factory, init_db
from modules.billing import models as _billing_models  # noqa: F401
from modules.conversations import models as _conversation_models  # noqa: F401
from modules.identity import models as _identity_models  # noqa: F401
from modules.knowledge import models as _knowledge_models  # noqa: F401
from modules.llm_gateway import models as _gateway_models  # noqa: F401
from modules.settings import models as _settings_models  # noqa: F401
from modules.settings import profile_models as _profile_models  # noqa: F401
from modules.usage import models as _usage_models  # noqa: F401
from modules.usage.recorder import UsageRecorder
from modules.workflows import models as _workflow_models  # noqa: F401


async def _flush_usage(request: Request, response: Response) -> None:
    """Persist buffered usage events once the response is done.

    Streaming responses record their usage while the body is consumed, so the flush has
    to wait for the end of the stream instead of running when the headers return.
    """
    recorder = getattr(request.state, "usage_recorder", None)
    if not isinstance(recorder, UsageRecorder):
        return

    if isinstance(response, StreamingResponse):
        original = response.body_iterator

        async def _drain() -> AsyncIterator[str | bytes | memoryview]:
            try:
                async for chunk in original:
                    yield chunk
            finally:
                await recorder.flush()

        response.body_iterator = _drain()
        return

    await recorder.flush()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage shared HTTP client and database engine across startup and shutdown."""
    settings: Settings = application.state.settings
    engine = create_engine(settings.database_url)
    application.state.db_engine = engine
    application.state.session_factory = create_session_factory(engine)
    if settings.db_auto_create:
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
    valid_api_keys = resolved_settings.parsed_api_keys()
    # Unauthenticated access is only ever permitted in local development.
    allow_open_access = resolved_settings.app_env == "development"
    limiter = SlidingWindowRateLimiter(max_requests=resolved_settings.rate_limit_per_minute)

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

    @application.middleware("http")
    async def security_and_rate_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        presented_key = extract_presented_api_key(request)
        principal = await resolve_principal(
            presented_key=presented_key,
            legacy_keys=valid_api_keys,
            allow_open=allow_open_access,
            session_factory=application.state.session_factory,
        )
        if principal is None:
            return build_unauthorized_response()
        request.state.principal = principal

        subject = f"user:{principal.tenant_id}:{principal.user_id}"
        decision = limiter.check(subject)
        if not decision.allowed:
            return build_rate_limited_response(decision)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        await _flush_usage(request, response)
        return response

    application.middleware("http")(request_context_middleware)
    application.include_router(chat.router)
    application.include_router(conversations.router)
    application.include_router(knowledge.router)
    application.include_router(usage.router)
    application.include_router(me.router)
    application.include_router(admin.router)
    application.include_router(providers.router)
    application.include_router(workflows.router)
    application.include_router(mcp.router)
    application.include_router(gateway.router)
    application.include_router(keys.router)

    @application.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        """Return basic service liveness status."""
        return {"status": "ok"}

    return application


app = create_app()
