"""In-memory cache implementation."""

import threading
from typing import Any


class MemoryCache:
    """
    Thread-safe in-memory cache that only keeps entries for a single cache key.

    When a different cache key is used with set(), all existing entries are cleared.
    This ensures bounded memory usage for demo purposes.

    Entries are organized by (cache_key, operation), e.g., ("abc123", "compile").
    """

    def __init__(self):
        self._cache: dict[str, Any] = {}  # operation -> value
        self._current_key: str | None = None
        self._lock = threading.Lock()

    @property
    def current_key(self) -> str | None:
        """Return the current active cache key."""
        with self._lock:
            return self._current_key

    def get(self, cache_key: str, operation: str) -> Any | None:
        """
        Get value from cache.

        Returns None if cache_key differs from current key (no implicit switch).
        """
        with self._lock:
            if self._current_key != cache_key:
                return None
            return self._cache.get(operation)

    def set(self, cache_key: str, operation: str, value: Any) -> None:
        """
        Set value in cache.

        If cache_key differs from current key, clears all entries first.
        """
        with self._lock:
            if self._current_key is not None and self._current_key != cache_key:
                self._cache.clear()
            self._current_key = cache_key
            self._cache[operation] = value

    def invalidate(self, cache_key: str, operation: str) -> None:
        """Remove a specific operation for a cache key."""
        with self._lock:
            if self._current_key == cache_key:
                self._cache.pop(operation, None)

    def has_operation(self, operation: str) -> bool:
        """Check if an operation exists for the current key."""
        with self._lock:
            return operation in self._cache

    def delete(self, key: str) -> None:
        """Delete value from cache (legacy single-key API)."""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached values and reset current key."""
        with self._lock:
            self._cache.clear()
            self._current_key = None

    def keys(self) -> list[str]:
        """Get all operation keys."""
        with self._lock:
            return list(self._cache.keys())
