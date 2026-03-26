import json
import math
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

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


def _sanitize_floats(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so JSON serialization succeeds."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _load_trajectory_file(path: Path) -> dict | None:
    """Load a trajectory JSON file, unwrapping double-encoded strings if needed.

    Some trajectory files are stored as a JSON string (the dict was serialised
    twice), so json.loads() returns a str rather than a dict.  This helper
    handles both cases transparently.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, str):
            raw = json.loads(raw)
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


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

    Lookup order:
    1. manifest trajectory_file (explicit pairing, handles any filename)
    2. glob {script_id}*.json (backward compat for simulated files)

    Uses make_cache_key(script_content, None, None) so layout matches cache design.
    Returns the data dict (with run_id injected) on success, None if not found.
    """

    def _try_file(path: Path) -> dict | None:
        data = _load_trajectory_file(path)
        if data is None:
            return None
        data["run_id"] = path.name
        script_content = _get_optimizer_script_content(script_id)
        if script_content is not None:
            key = make_cache_key(script_content, None, None)
            _cache.set(key, "trajectory", data, metadata={"script_id": script_id})
        return data

    # 1. Manifest-based explicit lookup
    manifest = _read_manifest()
    entry = next((e for e in manifest if e.get("id") == script_id), None)
    traj_filename = entry.get("trajectory_file") if entry else None
    if traj_filename:
        for directory in SEARCH_PATHS:
            path = directory / traj_filename
            if path.is_file():
                result = _try_file(path)
                if result is not None:
                    return result

    # 2. Glob fallback (simulated files named {script_id}*.json)
    for directory in SEARCH_PATHS:
        if not directory.exists():
            continue
        files = sorted(
            [f for f in directory.glob(f"{script_id}*.json") if "generated_code" not in f.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in files:
            result = _try_file(f)
            if result is not None:
                return result

    return None


def _cached_trajectory_files() -> list[Path]:
    """Return existing trajectory.json paths in the main cache, newest first."""
    paths = [
        _trajectory_path_for_key(k)
        for k in _cache.list_keys()
        if _trajectory_path_for_key(k).exists()
    ]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _find_trajectory_by_script_id(
    script_id: str,
    llm_name: str | None = None,
    temperature: float | None = None,
) -> dict | None:
    """Return newest trajectory from cache whose metadata.script_id equals script_id.

    If llm_name and/or temperature are given, prefer candidates whose
    sempipes_config.llm_for_code_generation matches; fall back to newest if none match.
    """
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

    if llm_name is None and temperature is None:
        return candidates[0][1]

    # Filter by llm/temp match
    def _matches(data: dict) -> bool:
        cfg = (data.get("sempipes_config") or {}).get("llm_for_code_generation") or {}
        if llm_name is not None and cfg.get("name") != llm_name:
            return False
        if temperature is not None:
            t = (cfg.get("parameters") or {}).get("temperature")
            if t is None or abs(float(t) - temperature) > 1e-6:
                return False
        return True

    for _, data in candidates:
        if _matches(data):
            return data
    # Exact llm/temp filter was given but nothing matched — return None so the
    # caller can fall back to _seed_from_legacy (which loads the canonical file).
    return None


def _extract_llm_option(data: dict) -> dict | None:
    """Extract {llm_name, temperature, label} from a trajectory dict, or None."""
    cfg = (data.get("sempipes_config") or {}).get("llm_for_code_generation") or {}
    name = cfg.get("name")
    temp = (cfg.get("parameters") or {}).get("temperature")
    if not name:
        return None
    temp_val = float(temp) if temp is not None else 0.0
    short = name.split("/")[-1]
    label = f"{short} (t={temp_val})"
    return {"llm_name": name, "temperature": temp_val, "label": label}


def _read_manifest() -> list[dict]:
    """Return the optimizer manifest entries."""
    path = _OPTIMIZER_SCRIPTS_DIR / "manifest.json"
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


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


@router.get("/options")
def get_optimizer_options(script_id: str):
    """Return available (llm_name, temperature) options for the given script id.

    Scans cache metadata and legacy trajectory files to find all unique LLM
    configurations for which a trajectory exists.
    """
    if script_id.endswith(".py"):
        script_id = script_id[:-3]

    seen: set[tuple[str, float]] = set()
    options: list[dict] = []

    # 1. Scan main cache
    for cache_key in _cache.list_keys():
        meta = _cache.get_metadata(cache_key, "trajectory")
        if meta and meta.get("script_id") == script_id:
            data = _cache.get(cache_key, "trajectory")
            if data is not None:
                opt = _extract_llm_option(data)
                if opt:
                    key = (opt["llm_name"], opt["temperature"])
                    if key not in seen:
                        seen.add(key)
                        options.append(opt)

    # 2. Always scan legacy files too — cache may be stale (different LLM from a prior run)
    # 2a. Manifest trajectory_file (handles non-script_id-prefixed filenames)
    manifest = _read_manifest()
    entry = next((e for e in manifest if e.get("id") == script_id), None)
    traj_filename = entry.get("trajectory_file") if entry else None
    if traj_filename:
        for directory in SEARCH_PATHS:
            path = directory / traj_filename
            if path.is_file():
                data = _load_trajectory_file(path)
                if data:
                    opt = _extract_llm_option(data)
                    if opt:
                        key = (opt["llm_name"], opt["temperature"])
                        if key not in seen:
                            seen.add(key)
                            options.append(opt)

    # 2b. Glob fallback for simulated / script_id-prefixed files
    for directory in SEARCH_PATHS:
        if not directory.exists():
            continue
        for f in sorted(
            [p for p in directory.glob(f"{script_id}*.json") if "generated_code" not in p.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            data = _load_trajectory_file(f)
            if data:
                opt = _extract_llm_option(data)
                if opt:
                    key = (opt["llm_name"], opt["temperature"])
                    if key not in seen:
                        seen.add(key)
                        options.append(opt)

    return options


@router.get("/final-code")
def get_final_code(script_id: str):
    """Return the final generated operator code dict for the given script id.

    Reads the code_file referenced in optimizer_scripts/manifest.json from
    .sempipes_trajectories/.
    """
    if script_id.endswith(".py"):
        script_id = script_id[:-3]

    manifest = _read_manifest()
    entry = next((e for e in manifest if e.get("id") == script_id), None)
    if entry is None or not entry.get("code_file"):
        raise HTTPException(status_code=404, detail=f"No code_file for script '{script_id}'")

    code_file = entry["code_file"]
    for directory in SEARCH_PATHS:
        path = directory / code_file
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error reading code file: {e}")

    raise HTTPException(status_code=404, detail=f"Code file '{code_file}' not found")


@router.get("/by-script")
def get_trajectory_by_script(
    script_id: str,
    llm_name: Optional[str] = Query(default=None),
    temperature: Optional[float] = Query(default=None),
):
    """Return the trajectory for the given optimizer script id.

    Optionally filter by llm_name and temperature; falls back to newest if no exact match.
    """
    if script_id.endswith(".py"):
        script_id = script_id[:-3]

    data = _find_trajectory_by_script_id(script_id, llm_name=llm_name, temperature=temperature)
    if data is None:
        data = _seed_from_legacy(script_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No trajectory found for script '{script_id}'",
        )
    return _sanitize_floats(data)


@router.get("/by-label")
def get_trajectory_by_label(label: str):
    """Return the most recent trajectory whose script_id contains label."""
    data = _find_trajectory_by_label(label)
    if data is not None:
        return _sanitize_floats(data)

    # Fall back to legacy directory and seed into cache
    for directory in SEARCH_PATHS:
        if not directory.exists():
            continue
        files = sorted(
            [p for p in directory.glob(f"*{label}*.json") if "generated_code" not in p.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            data = _load_trajectory_file(files[0])
            if data is not None:
                data["run_id"] = files[0].name
                script_id = files[0].stem.split("_simulated")[0]
                script_content = _get_optimizer_script_content(script_id)
                if script_content is not None:
                    key = make_cache_key(script_content, None, None)
                    _cache.set(key, "trajectory", data, metadata={"script_id": script_id})
                return _sanitize_floats(data)

    raise HTTPException(
        status_code=404,
        detail=f"No trajectory found for label '{label}'",
    )


@router.get("/latest")
def get_latest_trajectory():
    """Return the most recently modified trajectory."""
    for traj_file in _cached_trajectory_files():
        data = _load_trajectory_file(traj_file)
        if data is not None:
            return _sanitize_floats(data)

    # Fall back to legacy directory
    all_files = []
    for directory in SEARCH_PATHS:
        if directory.exists():
            all_files.extend(p for p in directory.glob("*.json") if "generated_code" not in p.name)

    if not all_files:
        raise HTTPException(status_code=404, detail="No trajectory files found")

    newest = max(all_files, key=lambda p: p.stat().st_mtime)
    data = _load_trajectory_file(newest)
    if data is None:
        raise HTTPException(status_code=500, detail="Error reading trajectory file")
    data["run_id"] = newest.name
    return _sanitize_floats(data)


@router.get("/status")
def get_optimizer_status():
    """Return {active: true} when at least one trajectory is available."""
    if _cached_trajectory_files():
        return {"active": True}

    for directory in SEARCH_PATHS:
        if directory.exists() and any(directory.glob("*.json")):
            return {"active": True}

    return {"active": False}
