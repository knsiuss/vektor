import time
from typing import Protocol


class KeyValueTTLStore(Protocol):
    """Shared TTL key-value interface (in-memory for dev, Redis for multi-worker prod)."""

    def set_if_absent(self, key: str, ttl_seconds: float) -> bool:
        """Atomically store key if absent/expired. Returns True if newly set, False if present."""
        ...


class InMemoryTTLStore:
    """Bounded in-memory TTL store for single-process development and tests."""

    def __init__(self, max_entries: int = 5000) -> None:
        self._max_entries = max_entries
        self._seen: dict[str, float] = {}

    def _prune(self, now: float) -> None:
        expired = [k for k, exp in self._seen.items() if exp <= now]
        for k in expired:
            self._seen.pop(k, None)
        if len(self._seen) > self._max_entries:
            oldest = sorted(self._seen.items(), key=lambda item: item[1])
            for k, _ in oldest[: len(self._seen) - self._max_entries]:
                self._seen.pop(k, None)

    def set_if_absent(self, key: str, ttl_seconds: float) -> bool:
        now = time.monotonic()
        self._prune(now)
        if key in self._seen and self._seen[key] > now:
            return False
        self._seen[key] = now + ttl_seconds
        return True
