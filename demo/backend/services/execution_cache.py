"""
Cache subprocess output for pipeline execution replay.
Keys are based on script ID + content hash to ensure cache is invalid if code changes.
"""
import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache directory: demo/.execution_cache
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_CACHE_DIR = _BACKEND_DIR.parent / ".execution_cache"


def cache_key(script_id: str, code: str, model: str = "", temperature: str = "") -> str:
    """Generate cache key from script_id, code content, model, and temperature."""
    normalized_code = code.strip()
    
    # Include model and temperature in the hash if provided
    hash_content = f"{normalized_code}|{model}|{temperature}"
    
    h = hashlib.sha256(hash_content.encode("utf-8")).hexdigest()[:12]
    safe_id = "".join(c for c in script_id if c.isalnum() or c in "-_")
    return f"{safe_id}__{h}"


def save(key: str, stdout: str) -> None:
    """Save subprocess stdout to cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = _CACHE_DIR / f"{key}.txt"
        cache_path.write_text(stdout, encoding="utf-8")
        logger.info(f"Saved execution cache to {cache_path}")
    except OSError as e:
        logger.warning(f"Failed to save execution cache: {e}")


def load(key: str) -> str | None:
    """Load subprocess stdout from cache if it exists."""
    cache_path = _CACHE_DIR / f"{key}.txt"
    if cache_path.exists():
        try:
            logger.info(f"Loading execution cache from {cache_path}")
            return cache_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"Failed to load execution cache: {e}")
    return None


def exists(key: str) -> bool:
    """Check if cache exists for key."""
    return (_CACHE_DIR / f"{key}.txt").exists()



def save_trajectory(key: str, traj_json: str) -> None:
    """Save optimizer trajectory JSON to cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = _CACHE_DIR / f"{key}_trajectory.json"
        cache_path.write_text(traj_json, encoding="utf-8")
        logger.info(f"Saved trajectory cache to {cache_path}")
    except OSError as e:
        logger.warning(f"Failed to save trajectory cache: {e}")


def load_trajectory(key: str) -> str | None:
    """Load optimizer trajectory JSON from cache if it exists."""
    cache_path = _CACHE_DIR / f"{key}_trajectory.json"
    if cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"Failed to load trajectory cache: {e}")
    return None


def clear() -> None:
    """Clear all cached executions and trajectories."""
    if _CACHE_DIR.exists():
        for f in _CACHE_DIR.glob("*.txt"):
            try:
                f.unlink()
            except OSError:
                pass
        for f in _CACHE_DIR.glob("*_trajectory.json"):
            try:
                f.unlink()
            except OSError:
                pass
