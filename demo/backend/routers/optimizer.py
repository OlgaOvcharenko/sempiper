import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(
    prefix="/api/optimizer",
    tags=["optimizer"],
)

# Determine repo root relative to this file
# This file is in demo/backend/routers/optimizer.py
# .parent -> routers
# .parent.parent -> backend
# .parent.parent.parent -> demo
# .parent.parent.parent.parent -> sempipes-demo (Repo Root)
# Determine repo root relative to this file
# This file is in demo/backend/routers/optimizer.py
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# We check both repo root (for manual runs) and backend root (for UI runs via execute_stream)
SEARCH_PATHS = [
    REPO_ROOT / ".sempipes_trajectories",
    REPO_ROOT / "demo/backend/.sempipes_trajectories"
]


@router.get("/by-label")
def get_trajectory_by_label(label: str):
    """
    Finds the most recent trajectory file containing the given label
    in the .sempipes_trajectories directory and returns its content.
    """
    matching_files = []
    
    for directory in SEARCH_PATHS:
        if directory.exists():
            pattern = f"*{label}*.json"
            matching_files.extend(list(directory.glob(pattern)))

    if not matching_files:
        raise HTTPException(
            status_code=404, 
            detail=f"No trajectory found for label '{label}' in search paths"
        )

    # Sort by modification time, newest first
    matching_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    # Pick the newest file
    newest_file = matching_files[0]

    try:
        with open(newest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Inject run_id (using filename) to help frontend detect new runs
        data["run_id"] = newest_file.name
        
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading trajectory file: {str(e)}")


@router.get("/by-script")
def get_trajectory_by_script(script_id: str):
    """
    Finds the most recent trajectory file whose name starts with the given script_id
    in the .sempipes_trajectories directory and returns its content.
    """
    if str(script_id).endswith(".py"):
         script_id = script_id[:-3]

    matching_files = []
    
    for directory in SEARCH_PATHS:
        if directory.exists():
            pattern = f"{script_id}*.json"
            matching_files.extend(list(directory.glob(pattern)))

    if not matching_files:
        raise HTTPException(
            status_code=404, 
            detail=f"No trajectory found for script '{script_id}' in search paths"
        )

    # Sort by modification time, newest first
    matching_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    # Pick the newest file
    newest_file = matching_files[0]

    try:
        with open(newest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Inject run_id (using filename) to help frontend detect new runs
        data["run_id"] = newest_file.name
        
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading trajectory file: {str(e)}")


@router.get("/latest")
def get_latest_trajectory():
    """
    Returns the most recently modified trajectory file across all search paths.
    Preferred over /by-label as it works regardless of operator name.
    """
    all_files = []
    for directory in SEARCH_PATHS:
        if directory.exists():
            all_files.extend(directory.glob("*.json"))

    if not all_files:
        raise HTTPException(status_code=404, detail="No trajectory files found")

    newest_file = max(all_files, key=lambda p: p.stat().st_mtime)

    try:
        with open(newest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["run_id"] = newest_file.name
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading trajectory file: {str(e)}")


@router.get("/status")
def get_optimizer_status():
    """
    Checks if there are any trajectory files in the trajectories directory.
    Returns: { "active": boolean }
    """
    for directory in SEARCH_PATHS:
        if directory.exists() and any(directory.glob("*.json")):
            return {"active": True}
            
    return {"active": False}
