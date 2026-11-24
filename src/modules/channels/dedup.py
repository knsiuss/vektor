from core.shared_store import InMemoryTTLStore, KeyValueTTLStore


class WebhookDeduplicator:
    """TTL deduplicator backed by a pluggable KeyValueTTLStore (in-memory or Redis)."""

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        max_entries: int = 5000,
        store: KeyValueTTLStore | None = None,
    ) -> None:
        self._ttl = ttl_seconds
        self._store: KeyValueTTLStore = store or InMemoryTTLStore(max_entries=max_entries)

    def mark_if_new(self, connector_id: str, event_id: str | None) -> bool:
        """Return True if event_id has not been processed recently, else False."""
        if not event_id:
            return True
        return self._store.set_if_absent(f"{connector_id}:{event_id}", self._ttl)
