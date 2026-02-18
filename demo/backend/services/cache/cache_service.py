"""Two-tier cache service (memory + file)."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .cache_format import CacheFormat
from .memory_cache import MemoryCache

logger = logging.getLogger(__name__)


class CacheService:
    """Two-tier cache: memory (fast) + file (persistent)."""

    def __init__(self, cache_dir: str | Path = ".cache"):
        self.cache_dir = Path(cache_dir)
        self.memory_cache = MemoryCache()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, cache_key: str, operation: str, format: CacheFormat = CacheFormat.JSON) -> Path:
        """Get file path for cache key."""
        op_dir = self.cache_dir / operation
        op_dir.mkdir(parents=True, exist_ok=True)
        return op_dir / f"{cache_key}.{format.value}"

    def get(self, cache_key: str, operation: str, format: CacheFormat = CacheFormat.JSON) -> Any | None:
        """Get from cache (memory first, then file)."""
        # Try memory cache first
        mem_key = f"{operation}:{cache_key}:{format.value}"
        value = self.memory_cache.get(mem_key)
        if value is not None:
            return value

        # Try file cache
        cache_path = self._get_cache_path(cache_key, operation, format)
        if not cache_path.exists():
            return None

        try:
            if format == CacheFormat.JSON:
                with open(cache_path, "r", encoding="utf-8") as f:
                    value = json.load(f)
            elif format == CacheFormat.SVG:
                with open(cache_path, "r", encoding="utf-8") as f:
                    value = json.load(f)  # SVG is stored as {"svg": "..."}
            else:
                with open(cache_path, "rb") as f:
                    value = f.read()

            # Store in memory cache
            self.memory_cache.set(mem_key, value)
            return value
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_path}: {e}")
            return None

    def set(self, cache_key: str, operation: str, value: Any, format: CacheFormat = CacheFormat.JSON) -> None:
        """Set in cache (both memory and file)."""
        # Store in memory cache
        mem_key = f"{operation}:{cache_key}:{format.value}"
        self.memory_cache.set(mem_key, value)

        # Store in file cache
        cache_path = self._get_cache_path(cache_key, operation, format)
        try:
            if format == CacheFormat.JSON or format == CacheFormat.SVG:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(value, f, indent=2)
            else:
                with open(cache_path, "wb") as f:
                    f.write(value if isinstance(value, bytes) else str(value).encode())
            logger.debug(f"Cached {operation} result at {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to write cache {cache_path}: {e}")

    def delete(self, cache_key: str, operation: str, format: CacheFormat = CacheFormat.JSON) -> None:
        """Delete from cache."""
        # Delete from memory
        mem_key = f"{operation}:{cache_key}:{format.value}"
        self.memory_cache.delete(mem_key)

        # Delete from file
        cache_path = self._get_cache_path(cache_key, operation, format)
        if cache_path.exists():
            try:
                os.remove(cache_path)
            except Exception as e:
                logger.warning(f"Failed to delete cache {cache_path}: {e}")

    def clear(self) -> None:
        """Clear all caches."""
        self.memory_cache.clear()
        # Note: File cache is not cleared to preserve persistence


# Global cache service instance
cache_service = CacheService()
