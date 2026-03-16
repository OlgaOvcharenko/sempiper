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
            # Store script as list of lines so the JSON file uses actual newlines
            serializable = dict(metadata)
            if isinstance(serializable.get("script"), str):
                serializable["script"] = serializable["script"].splitlines()
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2)
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
                data = json.load(f)
            # Re-join script lines stored as list back into a string
            if isinstance(data.get("script"), list):
                data["script"] = "\n".join(data["script"])
            return data
        except Exception as e:
            logger.warning(f"Failed to read metadata {metadata_path}: {e}")
            return None

    def ensure_metadata(self, cache_key: str, operation: str, metadata: dict[str, Any]) -> None:
        """Write metadata.json for this key only if it doesn't already exist on disk.

        Call this at cache-hit sites where the full metadata is available, so that
        a manually-deleted metadata.json gets recreated without re-running the pipeline.
        """
        metadata_path = self._get_metadata_path(cache_key, operation)
        if not metadata_path.exists():
            self._store_metadata(cache_key, operation, metadata)

    def get(self, cache_key: str, operation: str, format: CacheFormat = CacheFormat.JSON) -> Any | None:
        """Get from cache (memory first, then file).

        If the backing file has been manually deleted, the in-memory entry is
        evicted and None is returned — so individual files can be removed from
        disk to invalidate specific cache entries.
        """
        cache_path = self._get_cache_path(cache_key, operation, format)
        mem_op = self._mem_operation(operation, format)

        # Try memory cache first, but only if the backing file still exists
        value = self.memory_cache.get(cache_key, mem_op)
        if value is not None:
            if not cache_path.exists():
                self.memory_cache.invalidate(cache_key, mem_op)
                return None
            return value

        # Try file cache
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

            # Always ensure metadata.json exists for the key directory.
            # If metadata was provided, write it (full info).
            # If not provided but file is absent, write an empty placeholder so
            # every cache key directory always has a metadata.json.
            metadata_path = self._get_metadata_path(cache_key, operation)
            if metadata:
                self._store_metadata(cache_key, operation, metadata)
            elif not metadata_path.exists():
                self._store_metadata(cache_key, operation, {})
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

    def list_keys(self) -> list[str]:
        """Return cache key names (subdirectory names) that exist under cache_dir."""
        if not self.cache_dir.exists():
            return []
        return [item.name for item in self.cache_dir.iterdir() if item.is_dir()]

    def _next_archive_version(self, cache_key: str) -> str:
        """Return next archive version name (v1, v2, v3, …) for a specific key."""
        archive_dir = self.cache_dir / cache_key / "archive"
        if not archive_dir.exists():
            return "v1"
        existing = [
            int(d.name[1:])
            for d in archive_dir.iterdir()
            if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit()
        ]
        return f"v{max(existing) + 1}" if existing else "v1"

    def _archive_key_contents(self, cache_key: str) -> None:
        """Move current operation files for cache_key into its archive/vN/ subfolder."""
        key_dir = self.cache_dir / cache_key
        if not key_dir.exists():
            return
        items_to_archive = [item for item in key_dir.iterdir() if item.name != "archive"]
        if not items_to_archive:
            return
        version = self._next_archive_version(cache_key)
        archive_version_dir = key_dir / "archive" / version
        archive_version_dir.mkdir(parents=True, exist_ok=True)
        for item in items_to_archive:
            try:
                shutil.move(str(item), str(archive_version_dir / item.name))
                logger.debug(f"Archived {item} → {archive_version_dir / item.name}")
            except Exception as e:
                logger.warning(f"Failed to archive {item}: {e}")

    def clear_key(self, cache_key: str) -> None:
        """Clear all cache entries for a specific key — moves files to archive."""
        if self.memory_cache.current_key == cache_key:
            self.memory_cache.clear()
        self._archive_key_contents(cache_key)

    def clear(self) -> None:
        """Clear all caches (memory and file) — moves files to archive per key."""
        self.memory_cache.clear()
        if not self.cache_dir.exists():
            return
        for key_dir in self.cache_dir.iterdir():
            if key_dir.is_dir():
                self._archive_key_contents(key_dir.name)


# Global cache service instance
cache_service = CacheService()
