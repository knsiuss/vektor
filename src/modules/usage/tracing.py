"""Optional Langfuse observability wrapper with zero-overhead no-op fallback."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class _NoOpSpan:
    def update(self, **_kwargs: Any) -> None:
        return None


class Tracer:
    """Thin tracing facade that forwards spans to Langfuse when configured."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str = "https://cloud.langfuse.com",
    ) -> None:
        self._client: Any = None
        if enabled and public_key and secret_key:
            try:
                from langfuse import Langfuse  # type: ignore[import-not-found]

                self._client = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                )
            except ImportError:
                self._client = None

    @property
    def active(self) -> bool:
        """Return True when Langfuse client is initialized and active."""
        return self._client is not None

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        if self._client is None:
            yield _NoOpSpan()
            return
        trace_obj = self._client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
        )
        try:
            yield trace_obj
        finally:
            self._client.flush()

    @contextmanager
    def span(
        self,
        trace_obj: Any,
        name: str,
        *,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        if self._client is None or isinstance(trace_obj, _NoOpSpan):
            yield _NoOpSpan()
            return
        span_obj = trace_obj.span(name=name, input=input_data, metadata=metadata or {})
        try:
            yield span_obj
        finally:
            span_obj.end()
