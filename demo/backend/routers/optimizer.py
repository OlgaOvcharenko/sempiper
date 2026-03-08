import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from services.cache import cache_service, make_cache_key

# Use main cache; tests can replace this with an isolated CacheService
_cache = cache_service

router = APIRouter(
    prefix="/api/optimizer",
    tags=["optimizer"],
)

# Repo root (this file: demo/backend/routers/optimizer.py → 4 parents up)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_OPTIMIZER_SCRIPTS_DIR = REPO_ROOT / "optimizer_scripts"

# Legacy fallback directories: where real optimizer runs write their output and
# where the bundled simulated trajectories live.  Read-only in production;
# seeded into the main cache on first access.
SEARCH_PATHS = [
    REPO_ROOT / ".sempipes_trajectories",
    REPO_ROOT / "demo/backend/.sempipes_trajectories",
]

# Optimizer trajectories use the same cache as codegen: .cache/{cache_key}/trajectory.json
# with cache_key = make_cache_key(script, temperature, llm_name). Metadata stores script_id
# for by-script / by-label lookups.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_optimizer_script_content(script_id: str) -> str | None:
    """Return optimizer script source for script_id, or None if not found."""
    path = _OPTIMIZER_SCRIPTS_DIR / f"{script_id}.py"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _trajectory_path_for_key(cache_key: str) -> Path:
    """Path to trajectory.json for a cache key under the main cache."""
    return _cache.cache_dir / cache_key / "trajectory.json"


def _seed_from_legacy(script_id: str) -> dict | None:
    """Load trajectory for script_id from SEARCH_PATHS and seed the main cache.

    Uses make_cache_key(script_content, None, None) so layout matches cache design.
    Returns the data dict (with run_id injected) on success, None if not found.
    """
    for directory in SEARCH_PATHS:
        if not directory.exists():
            continue
        files = sorted(
            directory.glob(f"{script_id}*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            try:
                with open(files[0], "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["run_id"] = files[0].name
                script_content = _get_optimizer_script_content(script_id)
                if script_content is None:
                    return data  # return without caching if we can't compute key
                key = make_cache_key(script_content, None, None)
                _cache.set(
                    key, "trajectory", data,
                    metadata={"script_id": script_id},
                )
                return data
            except Exception:
                pass
    return None


def _cached_trajectory_files() -> list[Path]:
    """Return existing trajectory.json paths in the main cache, newest first."""
    paths = [
        _trajectory_path_for_key(k)
        for k in _cache.list_keys()
        if _trajectory_path_for_key(k).exists()
    ]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _find_trajectory_by_script_id(script_id: str) -> dict | None:
    """Return newest trajectory from cache whose metadata.script_id equals script_id."""
    candidates: list[tuple[float, dict]] = []
    for cache_key in _cache.list_keys():
        meta = _cache.get_metadata(cache_key, "trajectory")
        if meta and meta.get("script_id") == script_id:
            data = _cache.get(cache_key, "trajectory")
            if data is not None:
                path = _trajectory_path_for_key(cache_key)
                mtime = path.stat().st_mtime if path.exists() else 0.0
                candidates.append((mtime, data))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def _find_trajectory_by_label(label: str) -> dict | None:
    """Return newest trajectory from cache whose metadata.script_id contains label."""
    candidates: list[tuple[float, dict]] = []
    for cache_key in _cache.list_keys():
        meta = _cache.get_metadata(cache_key, "trajectory")
        if meta and label.lower() in (meta.get("script_id") or "").lower():
            data = _cache.get(cache_key, "trajectory")
            if data is not None:
                path = _trajectory_path_for_key(cache_key)
                mtime = path.stat().st_mtime if path.exists() else 0.0
                candidates.append((mtime, data))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/by-script")
def get_trajectory_by_script(script_id: str):
    """Return the trajectory for the given optimizer script id."""
    if script_id.endswith(".py"):
        script_id = script_id[:-3]

    data = _find_trajectory_by_script_id(script_id)
    if data is None:
        data = _seed_from_legacy(script_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No trajectory found for script '{script_id}'",
        )
    return data


@router.get("/by-label")
def get_trajectory_by_label(label: str):
    """Return the most recent trajectory whose script_id contains label."""
    data = _find_trajectory_by_label(label)
    if data is not None:
        return data

    # Fall back to legacy directory and seed into cache
    for directory in SEARCH_PATHS:
        if not directory.exists():
            continue
        files = sorted(
            directory.glob(f"*{label}*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            try:
                with open(files[0], "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["run_id"] = files[0].name
                script_id = files[0].stem.split("_simulated")[0]
                script_content = _get_optimizer_script_content(script_id)
                if script_content is not None:
                    key = make_cache_key(script_content, None, None)
                    _cache.set(
                        key, "trajectory", data,
                        metadata={"script_id": script_id},
                    )
                return data
            except Exception:
                pass

    raise HTTPException(
        status_code=404,
        detail=f"No trajectory found for label '{label}'",
    )


@router.get("/latest")
def get_latest_trajectory():
    """Return the most recently modified trajectory."""
    for traj_file in _cached_trajectory_files():
        try:
            with open(traj_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Fall back to legacy directory
    all_files = []
    for directory in SEARCH_PATHS:
        if directory.exists():
            all_files.extend(directory.glob("*.json"))

    if not all_files:
        raise HTTPException(status_code=404, detail="No trajectory files found")

    newest = max(all_files, key=lambda p: p.stat().st_mtime)
    try:
        with open(newest, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["run_id"] = newest.name
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading trajectory file: {e}")


@router.get("/status")
def get_optimizer_status():
    """Return {active: true} when at least one trajectory is available."""
    if _cached_trajectory_files():
        return {"active": True}

    for directory in SEARCH_PATHS:
        if directory.exists() and any(directory.glob("*.json")):
            return {"active": True}

    return {"active": False}
