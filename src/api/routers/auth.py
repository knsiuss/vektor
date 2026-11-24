"""Browser login endpoints: Google and GitHub via OAuth, plus session status."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal, get_settings
from core.config.settings import Settings
from modules.identity.oauth import (
    PROVIDERS,
    OAuthError,
    build_authorize_url,
    fetch_profile,
    sign_state,
    verify_state,
)
from modules.identity.oauth_repo import OAuthRepository
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

STATE_COOKIE = "vektor_oauth_state"
SESSION_COOKIE = "vektor_session"


def _provider(value: str) -> str:
    if value not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider.")
    return value


def _credentials(settings: Settings, provider: str) -> tuple[str, str]:
    if provider == "google":
        client_id = settings.oauth_google_client_id
        secret = settings.oauth_google_client_secret
    else:
        client_id = settings.oauth_github_client_id
        secret = settings.oauth_github_client_secret
    if not client_id or secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider} login is not configured on this server.",
        )
    return client_id, secret.get_secret_value()


def _session_secret(settings: Settings) -> str:
    if settings.auth_session_secret is not None:
        return settings.auth_session_secret.get_secret_value()
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Login is not configured: VEKTOR_AUTH_SESSION_SECRET is missing.",
    )


@router.get("/providers")
async def list_providers(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, bool]:
    """Tell the login screen which buttons to show."""
    return {
        "google": bool(settings.oauth_google_client_id and settings.oauth_google_client_secret),
        "github": bool(settings.oauth_github_client_id and settings.oauth_github_client_secret),
    }


@router.get("/{provider}/start")
async def start_login(
    provider: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Redirect the browser to the provider's consent screen."""
    name = _provider(provider)
    client_id, _ = _credentials(settings, name)
    state = sign_state(name, _session_secret(settings))
    url = build_authorize_url(
        name,
        client_id=client_id,
        public_frontend_url=settings.public_frontend_url,
        state=state,
    )
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.public_frontend_url.startswith("https://"),
        path="/",
    )
    return response


@router.get("/{provider}/callback")
async def login_callback(
    provider: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> Response:
    """Exchange the code, link the account, and start a browser session."""
    name = _provider(provider)
    home = f"{settings.public_frontend_url.rstrip('/')}/?login=failed"
    if error or not code or not state:
        return RedirectResponse(home, status_code=status.HTTP_302_FOUND)

    cookie_state = request.cookies.get(STATE_COOKIE)
    try:
        verify_state(state, name, _session_secret(settings))
        if cookie_state and not _same(state, cookie_state):
            raise OAuthError("Login state does not match this browser.")
    except OAuthError:
        return RedirectResponse(home, status_code=status.HTTP_302_FOUND)

    client_id, client_secret = _credentials(settings, name)
    try:
        profile = await fetch_profile(
            name,
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            public_frontend_url=settings.public_frontend_url,
        )
    except OAuthError:
        return RedirectResponse(home, status_code=status.HTTP_302_FOUND)

    repo = OAuthRepository(session=session)
    account = await repo.upsert_account(profile)
    raw_session = await repo.create_session(account, days=settings.auth_session_days)

    response = RedirectResponse(
        f"{settings.public_frontend_url.rstrip('/')}/",
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        max_age=settings.auth_session_days * 86_400,
        httponly=True,
        samesite="lax",
        secure=settings.public_frontend_url.startswith("https://"),
        path="/",
    )
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.get("/me")
async def current_user(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str | bool | None]:
    """Identity of the signed-in user, for the sidebar and the login gate."""
    account = await OAuthRepository(session=session).account_for(
        principal.user_id, principal.tenant_id
    )
    return {
        "user_id": principal.user_id,
        "tenant_id": principal.tenant_id,
        "is_admin": principal.is_admin,
        "name": account.name if account else None,
        "email": account.email if account else None,
        "avatar_url": account.avatar_url if account else None,
        "provider": account.provider if account else None,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Drop the server-side session and clear the cookie."""
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        await OAuthRepository(session=session).revoke(raw)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


def _same(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
