import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from services.cache.cache_service import CacheService

router = APIRouter(
    prefix="/api/optimizer",
    tags=["optimizer"],
)

# Repo root (this file: demo/backend/routers/optimizer.py → 4 parents up)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Legacy fallback directories: where real optimizer runs write their output and
# where the bundled simulated trajectories live.  Read-only in production;
# seeded into _trajectory_cache on first access.
SEARCH_PATHS = [
    REPO_ROOT / ".sempipes_trajectories",
    REPO_ROOT / "demo/backend/.sempipes_trajectories",
]

# Primary store for optimizer trajectories.
# Cache key = script_id (e.g. "optimise_fraud"), operation = "trajectory".
# A dedicated CacheService avoids memory-cache key conflicts with the
# main code-gen cache (services/cache/cache_service.py uses ".cache").
_trajectory_cache = CacheService(".cache/optimizer")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _seed_from_legacy(script_id: str) -> dict | None:
    """Load trajectory for script_id from SEARCH_PATHS and seed the cache.

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
                _trajectory_cache.set(script_id, "trajectory", data)
                return data
            except Exception:
                pass
    return None


def _cached_trajectory_files() -> list[Path]:
    """Return existing trajectory.json paths inside the cache dir, newest first."""
    cache_dir = _trajectory_cache.cache_dir
    if not cache_dir.exists():
        return []
    paths = [
        d / "trajectory.json"
        for d in cache_dir.iterdir()
        if d.is_dir()
    ]
    return sorted(
        (p for p in paths if p.exists()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/by-script")
def get_trajectory_by_script(script_id: str):
    """Return the trajectory for the given optimizer script id."""
    if script_id.endswith(".py"):
        script_id = script_id[:-3]

    data = _trajectory_cache.get(script_id, "trajectory")
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
    # Check cache: each subdirectory name IS the script_id
    for traj_file in _cached_trajectory_files():
        if label.lower() in traj_file.parent.name.lower():
            try:
                with open(traj_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

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
                # Derive script_id by dropping the "_simulated" suffix if present
                script_id = files[0].stem.split("_simulated")[0]
                _trajectory_cache.set(script_id, "trajectory", data)
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
    # Check cache first
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
