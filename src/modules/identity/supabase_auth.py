"""Verify Supabase Auth JWTs (ES256 via JWKS or HS256 via shared secret) and map to Principals."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from fastapi import Request
from jwt import PyJWKClient

from modules.identity.principal import ROLE_MEMBER, Principal

logger = logging.getLogger(__name__)


def is_supabase_configured() -> bool:
    """True when this deployment expects Supabase-issued tokens (env or .env file)."""
    keys = ("VEKTOR_SUPABASE_URL", "SUPABASE_URL", "VEKTOR_SUPABASE_JWT_SECRET", "SUPABASE_JWT_SECRET")
    if any(os.getenv(name) for name in keys):
        return True
    try:
        from dotenv import dotenv_values

        values = dotenv_values(".env")
    except Exception:  # noqa: BLE001 - a missing dotenv file simply means "not configured"
        return False
    return any(values.get(name) for name in keys)


def extract_bearer_jwt(request: Request) -> str | None:
    """Return the raw JWT from Authorization: Bearer <token>, if it looks like a JWT."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token if token.count(".") == 2 else None


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


def verify_supabase_jwt(token: str, *, secret: str | None = None) -> Principal | None:
    """Verify a Supabase JWT (ES256/RS256 via JWKS or HS256 via secret) and return a Principal."""
    payload: dict[str, Any] | None = None
    supabase_url = (
        os.getenv("VEKTOR_SUPABASE_URL")
        or os.getenv("SUPABASE_URL")
        or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    )
    if not supabase_url:
        from dotenv import dotenv_values

        env_path = Path(__file__).resolve().parents[3] / ".env"
        env_vals = dotenv_values(env_path)
        supabase_url = env_vals.get("VEKTOR_SUPABASE_URL") or env_vals.get("SUPABASE_URL")
    if supabase_url:
        jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        try:
            signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
                leeway=60,
            )
        except jwt.PyJWTError as exc:
            logger.warning("supabase_jwks_decode_failed: %s", exc)
            payload = None

    if payload is None:
        jwt_secret = (
            secret
            or os.getenv("VEKTOR_SUPABASE_JWT_SECRET")
            or os.getenv("SUPABASE_JWT_SECRET")
        )
        if not jwt_secret:
            return None
        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.PyJWTError:
            return None

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        return None

    return Principal(
        user_id=sub,
        tenant_id=f"user:{sub}",
        roles=frozenset({ROLE_MEMBER}),
    )
