import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.identity.principal import Principal
from modules.usage.models import UsageEvent

logger = logging.getLogger("vektor.usage")

UsageHook = Callable[[str, int, int, int], None]
"""Called as hook(model, prompt_tokens, completion_tokens, total_tokens)."""


class UsageRecorder:
    """Collects usage events during a request and writes them after the request finishes.

    Events are buffered in memory and persisted by ``flush()`` in a fresh session, after the
    request's own transaction has ended. Writing in the middle of a request would contend for
    SQLite's single write lock with the request's open transaction. Metering is best effort:
    a failure to persist is logged and never breaks the user's request.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        principal: Principal,
    ) -> None:
        self._session_factory = session_factory
        self._principal = principal
        self._pending: list[UsageEvent] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def record(
        self,
        *,
        kind: str,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """Buffer one model call. Never raises."""
        self._pending.append(
            UsageEvent(
                tenant_id=self._principal.tenant_id,
                user_id=self._principal.user_id,
                kind=kind,
                provider=provider[:64],
                model=model[:128],
                prompt_tokens=max(0, prompt_tokens),
                completion_tokens=max(0, completion_tokens),
                total_tokens=max(0, total_tokens),
            )
        )

    def hook(self, *, kind: str, provider: str) -> UsageHook:
        """Return a callback that adapters call after each upstream request."""

        def _on_usage(model: str, prompt: int, completion: int, total: int) -> None:
            self.record(
                kind=kind,
                provider=provider,
                model=model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
            )

        return _on_usage

    async def flush(self) -> None:
        """Persist buffered events. Safe to call repeatedly; failures are logged, not raised."""
        if not self._pending:
            return
        events, self._pending = self._pending, []
        try:
            async with self._session_factory() as session:
                session.add_all(events)
                await session.commit()
        except Exception:
            logger.exception("usage_flush_failed dropped_events=%d", len(events))
