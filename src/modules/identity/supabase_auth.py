"""Verify Supabase Auth JWTs and map them to Vektor Principals."""

from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import Request

from modules.identity.principal import ROLE_MEMBER, Principal


def extract_bearer_jwt(request: Request) -> str | None:
    """Return the raw JWT from Authorization: Bearer <token>, if it looks like a JWT."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token if token.count(".") == 2 else None


def verify_supabase_jwt(token: str, *, secret: str | None = None) -> Principal | None:
    """Verify a Supabase HS256 JWT and return a user-scoped Principal, or None if invalid."""
    jwt_secret = (
        secret
        or os.getenv("VEKTOR_SUPABASE_JWT_SECRET")
        or os.getenv("SUPABASE_JWT_SECRET")
    )
    if not jwt_secret:
        return None
    try:
        payload: dict[str, Any] = jwt.decode(
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
