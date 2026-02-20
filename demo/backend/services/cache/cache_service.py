"""Two-tier cache service (memory + file)."""

import json
import logging
import os
import shutil
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
        """Get file path for cache key.

        Structure: .cache/{cache_key}/{operation}.{format}
        Example: .cache/9f9c1f2cb7698818/compile.json

        Note: Does not create the directory - caller should handle directory creation.
        """
        key_dir = self.cache_dir / cache_key
        return key_dir / f"{operation}.{format.value}"

    def _mem_operation(self, operation: str, format: CacheFormat) -> str:
        """Create memory cache operation key including format."""
        return f"{operation}:{format.value}"

    def _get_metadata_path(self, cache_key: str, operation: str) -> Path:
        """Get file path for metadata JSON.

        Structure: .cache/{cache_key}/metadata.json

        Note: operation parameter is kept for backward compatibility but not used.
        All metadata for a cache key is stored in a single metadata.json file.
        Does not create the directory - caller should handle directory creation.
        """
        key_dir = self.cache_dir / cache_key
        return key_dir / "metadata.json"

    def _store_metadata(self, cache_key: str, operation: str, metadata: dict[str, Any]) -> None:
        """Store metadata (script, model, temperature) alongside cache entry."""
        metadata_path = self._get_metadata_path(cache_key, operation)
        try:
            # Create directory if it doesn't exist
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            logger.debug(f"Stored metadata at {metadata_path}")
        except Exception as e:
            logger.warning(f"Failed to write metadata {metadata_path}: {e}")

    def get_metadata(self, cache_key: str, operation: str) -> dict[str, Any] | None:
        """Get metadata for a cache entry.

        Returns:
            Metadata dict with keys like 'script', 'model', 'temperature', or None if not found
        """
        metadata_path = self._get_metadata_path(cache_key, operation)
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read metadata {metadata_path}: {e}")
            return None

    def get(self, cache_key: str, operation: str, format: CacheFormat = CacheFormat.JSON) -> Any | None:
        """Get from cache (memory first, then file)."""
        # Try memory cache first
        mem_op = self._mem_operation(operation, format)
        value = self.memory_cache.get(cache_key, mem_op)
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
                    value = f.read()  # SVG is stored as plain text
            else:
                with open(cache_path, "rb") as f:
                    value = f.read()

            # Store in memory cache (this may clear if cache_key changed)
            self.memory_cache.set(cache_key, mem_op, value)
            return value
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_path}: {e}")
            return None

    def set(
        self,
        cache_key: str,
        operation: str,
        value: Any,
        format: CacheFormat = CacheFormat.JSON,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set in cache (both memory and file).

        Args:
            cache_key: Cache key (hash)
            operation: Operation name (compile, execute, etc.)
            value: Value to cache
            format: Cache format (JSON, SVG, etc.)
            metadata: Optional metadata (script, model, temperature) to store alongside cache
        """
        # Store in memory cache (clears if cache_key differs from current)
        mem_op = self._mem_operation(operation, format)
        self.memory_cache.set(cache_key, mem_op, value)

        # Store in file cache
        cache_path = self._get_cache_path(cache_key, operation, format)
        try:
            # Create directory if it doesn't exist
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            if format == CacheFormat.JSON:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(value, f, indent=2)
            elif format == CacheFormat.SVG:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(value)  # Write SVG as plain text
            else:
                with open(cache_path, "wb") as f:
                    f.write(value if isinstance(value, bytes) else str(value).encode())
            logger.debug(f"Cached {operation} result at {cache_path}")

            # Store metadata if provided
            if metadata:
                self._store_metadata(cache_key, operation, metadata)
        except Exception as e:
            logger.warning(f"Failed to write cache {cache_path}: {e}")

    def delete(self, cache_key: str, operation: str, format: CacheFormat = CacheFormat.JSON) -> None:
        """Delete from cache (including metadata)."""
        # Delete from memory
        mem_op = self._mem_operation(operation, format)
        self.memory_cache.invalidate(cache_key, mem_op)

        # Delete from file
        cache_path = self._get_cache_path(cache_key, operation, format)
        if cache_path.exists():
            try:
                os.remove(cache_path)
            except Exception as e:
                logger.warning(f"Failed to delete cache {cache_path}: {e}")

        # Delete metadata
        metadata_path = self._get_metadata_path(cache_key, operation)
        if metadata_path.exists():
            try:
                os.remove(metadata_path)
            except Exception as e:
                logger.warning(f"Failed to delete metadata {metadata_path}: {e}")

    def invalidate(self, cache_key: str, operation: str, format: CacheFormat = CacheFormat.JSON) -> None:
        """Alias for delete() - removes specific cache entry."""
        self.delete(cache_key, operation, format)

    def clear(self) -> None:
        """Clear all caches (memory and file)."""
        self.memory_cache.clear()
        # Clear file cache by removing all subdirectories
        if self.cache_dir.exists():
            for item in self.cache_dir.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete cache item {item}: {e}")


# Global cache service instance
cache_service = CacheService()
