import json
import time
from collections import OrderedDict


class ToolResultCache:
    """In-memory TTL cache for deterministic read-only tool calls."""

    def __init__(self, *, ttl_seconds: float = 60.0, max_entries: int = 256) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: OrderedDict[tuple[str, str], tuple[float, str]] = OrderedDict()

    @staticmethod
    def normalize_args(raw_arguments: str) -> str:
        try:
            parsed = json.loads(raw_arguments or "{}")
            return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        except ValueError:
            return raw_arguments.strip()

    def get(self, tool_name: str, raw_arguments: str) -> str | None:
        key = (tool_name, self.normalize_args(raw_arguments))
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, output = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return output

    def set(self, tool_name: str, raw_arguments: str, output: str) -> None:
        key = (tool_name, self.normalize_args(raw_arguments))
        self._store[key] = (time.monotonic() + self._ttl, output)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)
