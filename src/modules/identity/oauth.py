"""OAuth login support for Google and GitHub.

Only the authorization-code flow is implemented: the browser is redirected to the provider,
then the callback exchanges the code and creates a server-side session. State is signed with
HMAC so a forged callback cannot bind an attacker's account to an existing session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

Provider = Literal["google", "github"]

STATE_TTL_SECONDS = 600


class OAuthError(Exception):
    """Raised when a login attempt cannot be completed."""


@dataclass(frozen=True)
class ProviderConfig:
    """Endpoints and scopes for one identity provider."""

    provider: Provider
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str


PROVIDERS: dict[str, ProviderConfig] = {
    "google": ProviderConfig(
        provider="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
    ),
    "github": ProviderConfig(
        provider="github",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
    ),
}


@dataclass(frozen=True)
class OAuthProfile:
    """Normalized account details shared by both providers."""

    provider: str
    provider_user_id: str
    email: str | None
    name: str | None
    avatar_url: str | None


def redirect_uri(public_frontend_url: str, provider: str) -> str:
    """Browser-facing callback, proxied by the frontend so cookies stay on one origin."""
    return f"{public_frontend_url.rstrip('/')}/api/backend/auth/{provider}/callback"


def build_authorize_url(
    provider: str,
    *,
    client_id: str,
    public_frontend_url: str,
    state: str,
) -> str:
    """Compose the provider consent URL for a browser redirect."""
    config = _config(provider)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(public_frontend_url, provider),
        "scope": config.scope,
        "state": state,
        "response_type": "code",
    }
    if provider == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    return f"{config.authorize_url}?{urlencode(params)}"


async def fetch_profile(
    provider: str,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    public_frontend_url: str,
    client: httpx.AsyncClient | None = None,
) -> OAuthProfile:
    """Exchange the authorization code and normalize the provider's profile payload."""
    config = _config(provider)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=15.0)
    try:
        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri(public_frontend_url, provider),
            "grant_type": "authorization_code",
        }
        token_response = await http.post(
            config.token_url,
            data=token_payload,
            headers={"Accept": "application/json"},
        )
        if token_response.status_code >= 400:
            raise OAuthError("Provider rejected the login code.")
        token = token_response.json()
        access_token = token.get("access_token") if isinstance(token, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError("Provider did not return an access token.")

        profile_response = await http.get(
            config.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if profile_response.status_code >= 400:
            raise OAuthError("Provider did not return a profile.")
        payload = profile_response.json()
    except httpx.HTTPError as exc:
        raise OAuthError("Provider is unreachable.") from exc
    finally:
        if owns_client:
            await http.aclose()

    return _normalize(provider, payload)


def _normalize(provider: str, payload: Any) -> OAuthProfile:
    if not isinstance(payload, dict):
        raise OAuthError("Provider returned an unexpected profile payload.")
    if provider == "google":
        subject = payload.get("sub")
        user_id = str(subject) if subject is not None else ""
        email = payload.get("email")
        name = payload.get("name")
        avatar = payload.get("picture")
    else:
        raw_id = payload.get("id")
        user_id = str(raw_id) if raw_id is not None else ""
        email = payload.get("email")
        name = payload.get("name") or payload.get("login")
        avatar = payload.get("avatar_url")

    if not user_id:
        raise OAuthError("Provider profile is missing an account id.")
    return OAuthProfile(
        provider=provider,
        provider_user_id=user_id,
        email=email if isinstance(email, str) else None,
        name=name if isinstance(name, str) else None,
        avatar_url=avatar if isinstance(avatar, str) else None,
    )


def _config(provider: str) -> ProviderConfig:
    config = PROVIDERS.get(provider)
    if config is None:
        raise OAuthError(f"Unsupported provider '{provider}'.")
    return config


def sign_state(
    provider: str,
    secret: str,
    *,
    origin: str = "",
    now: float | None = None,
) -> str:
    """Return a tamper-proof state token carrying the provider, the return origin, and an expiry."""
    issued = int(now if now is not None else time.time())
    payload = json.dumps(
        {"p": provider, "n": secrets.token_urlsafe(12), "t": issued, "o": origin}
    )
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def verify_state(
    state: str, expected_provider: str, secret: str, *, now: float | None = None
) -> dict:
    """Validate the state and return its payload (provider, origin, issued-at)."""
    encoded, _, signature = state.partition(".")
    if not encoded or not signature:
        raise OAuthError("Missing login state.")
    expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise OAuthError("Login state signature is invalid.")
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode()).decode())
    except (ValueError, TypeError) as exc:
        raise OAuthError("Login state is malformed.") from exc
    if payload.get("p") != expected_provider:
        raise OAuthError("Login state was issued for another provider.")
    issued = payload.get("t")
    current = now if now is not None else time.time()
    if not isinstance(issued, (int, float)) or current - issued > STATE_TTL_SECONDS:
        raise OAuthError("Login state has expired.")
    return payload
