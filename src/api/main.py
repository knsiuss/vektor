from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from starlette.responses import StreamingResponse

from api.auth import resolve_principal
from api.middleware import request_context_middleware
from api.routers import (
    admin,
    artifact_evidence,
    artifacts,
    chat,
    conversations,
    gateway,
    keys,
    knowledge,
    mcp,
    me,
    memory,
    providers,
    public_chat,
    usage,
    widgets,
    workflows,
)
from api.routers import (
    auth as auth_router,
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
from modules.widgets import models as _widgets_models  # noqa: F401
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
    # Unauthenticated access is only ever permitted in local development, and never when
    # Supabase auth is configured: otherwise every browser silently becomes the dev user.
    supabase_auth_enabled = bool(
        resolved_settings.supabase_url or resolved_settings.supabase_jwt_secret
    )
    allow_open_access = (
        resolved_settings.app_env == "development" and not supabase_auth_enabled
    )
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

    cors_origins = [o.strip() for o in resolved_settings.cors_origins.split(",") if o.strip()]
    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "x-api-key", "x-vektor-backend"],
        )

    @application.middleware("http")
    async def security_and_rate_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        # Public login endpoints run before a session exists; /auth/me and /auth/logout
        # still resolve normally so development open access keeps working.
        path = request.url.path
        if path == "/api/v1/auth/providers" or (
            path.startswith("/api/v1/auth/")
            and (path.endswith("/start") or path.endswith("/callback"))
        ):
            return await call_next(request)

        if path.startswith("/api/v1/public/"):
            origin = request.headers.get("origin")
            cors_headers = {
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Vary": "Origin",
            }
            if origin:
                cors_headers["Access-Control-Allow-Origin"] = origin
            if request.method == "OPTIONS":
                return Response(status_code=204, headers=cors_headers)

            client_ip = request.client.host if request.client else "unknown"
            decision = limiter.check(f"public:{client_ip}")
            if not decision.allowed:
                return build_rate_limited_response(decision)
            response = await call_next(request)
            for key, value in cors_headers.items():
                response.headers[key] = value
            await _flush_usage(request, response)
            return response

        from modules.identity.supabase_auth import extract_bearer_jwt, verify_supabase_jwt

        bearer_jwt = extract_bearer_jwt(request)
        if bearer_jwt is not None:
            principal = verify_supabase_jwt(bearer_jwt)
        else:
            presented_key = extract_presented_api_key(request)
            principal = await resolve_principal(
                presented_key=presented_key,
                session_token=request.cookies.get("vektor_session"),
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
    application.include_router(auth_router.router)
    application.include_router(chat.router)
    application.include_router(conversations.router)
    application.include_router(knowledge.router)
    application.include_router(usage.router)
    application.include_router(me.router)
    application.include_router(memory.router)
    application.include_router(admin.router)
    application.include_router(artifacts.router)
    application.include_router(artifact_evidence.router)
    application.include_router(providers.router)
    application.include_router(workflows.router)
    application.include_router(mcp.router)
    application.include_router(gateway.router)
    application.include_router(keys.router)
    application.include_router(widgets.router)
    application.include_router(public_chat.router)

    @application.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        """Return basic service liveness status."""
        return {"status": "ok"}

    return application


app = create_app()
