import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any


class InboxEventBus:
    """Tenant-scoped in-process async pub/sub bus for real-time Inbox SSE."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def publish(self, tenant_id: str, event_type: str, data: dict[str, Any]) -> None:
        queues = list(self._subscribers.get(tenant_id, ()))
        payload = {"event": event_type, "data": data}
        for queue in queues:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(payload)

    async def subscribe(self, tenant_id: str) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(tenant_id, set()).add(queue)
        try:
            while True:
                item = await queue.get()
                event_name = str(item.get("event", "message"))
                body = json.dumps(item.get("data", {}), ensure_ascii=False)
                yield f"event: {event_name}\ndata: {body}\n\n"
        finally:
            subs = self._subscribers.get(tenant_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(tenant_id, None)


inbox_event_bus = InboxEventBus()
