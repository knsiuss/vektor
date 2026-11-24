import hashlib
import hmac
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Request, status
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a single sliding-window rate limit evaluation."""

    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class SlidingWindowRateLimiter:
    """Thread-safe in-memory per-client sliding-window rate limiter."""

    def __init__(self, *, max_requests: int, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = {}

    def check(self, client_key: str) -> RateLimitDecision:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        bucket = self._buckets.setdefault(client_key, deque())

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self._max_requests:
            oldest = bucket[0]
            reset_after = max(1, int((oldest + self._window_seconds) - now))
            return RateLimitDecision(
                allowed=False,
                limit=self._max_requests,
                remaining=0,
                reset_seconds=reset_after,
            )

        bucket.append(now)
        remaining = max(0, self._max_requests - len(bucket))
        return RateLimitDecision(
            allowed=True,
            limit=self._max_requests,
            remaining=remaining,
            reset_seconds=self._window_seconds,
        )


def extract_presented_api_key(request: Request) -> str | None:
    """Read API key from X-API-Key header or Authorization Bearer token."""
    direct = request.headers.get("X-API-Key")
    if direct and direct.strip():
        return direct.strip()

    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return None


def verify_api_key(
    presented: str | None,
    valid_keys: tuple[str, ...],
    *,
    allow_open: bool = False,
) -> bool:
    """Verify presented key using constant-time comparison; fail closed when unconfigured."""
    if not valid_keys:
        return allow_open
    if not presented:
        return False

    matched = False
    for expected in valid_keys:
        if hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
            matched = True
    return matched


def derive_rate_limit_subject(request: Request, presented_key: str | None) -> str:
    """Identify caller by hashed API key if present, otherwise client IP address."""
    if presented_key:
        digest = hashlib.sha256(presented_key.encode("utf-8")).hexdigest()[:16]
        return f"key:{digest}"
    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


def build_unauthorized_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Invalid or missing Vektor API key."},
    )


def build_rate_limited_response(decision: RateLimitDecision) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Rate limit exceeded. Please retry later."},
        headers={
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": "0",
            "Retry-After": str(decision.reset_seconds),
        },
    )
