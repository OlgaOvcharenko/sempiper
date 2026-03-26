#!/usr/bin/env python
"""
Profile dynamic compile by calling the backend API (simple script).

Requires the backend to be running (e.g. make run or uvicorn from demo/backend).
Usage:
  poetry run python demo/backend/scripts/profile_compile_via_api.py [simple|medium|full]
  BASE_URL=http://localhost:8000 poetry run python demo/backend/scripts/profile_compile_via_api.py simple

Sends POST /api/compile with use_dynamic=True and X-Compile-Timing: 1,
then prints the compile_timings_ms breakdown from the response.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

# Repo root: this script is at demo/backend/scripts/
_script_dir = Path(__file__).resolve().parent
_backend = _script_dir.parent
_repo_root = _backend.parent.parent
_scripts_dir = _repo_root / "pipeline_scripts"

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def load_script(name: str) -> str:
    manifest_path = _scripts_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"No manifest at {manifest_path}")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    entry = next((e for e in manifest if e["id"] == name), None)
    if not entry:
        raise SystemExit(f"Unknown script: {name}. Choose from {[e['id'] for e in manifest]}")
    path = _scripts_dir / entry["file"]
    if not path.is_file():
        raise SystemExit(f"Script file not found: {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "simple"
    script = load_script(name)
    url = f"{BASE_URL.rstrip('/')}/api/compile"
    print(f"Profiling dynamic compile for script: {name} ({len(script)} chars)", flush=True)
    print(f"POST {url} (X-Compile-Timing: 1, use_dynamic=True)", flush=True)

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            url,
            json={"input_code": script, "use_dynamic": True},
            headers={"X-Compile-Timing": "1"},
        )
    resp.raise_for_status()
    data = resp.json()

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    timings = data.get("compile_timings_ms")

    print(f"Nodes: {len(nodes)}, Edges: {len(edges)}", flush=True)
    if timings:
        print("Timings (ms), sorted by duration:", flush=True)
        for k, v in sorted(timings.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {k}: {v:.2f}", flush=True)
        total = sum(timings.values())
        print(f"  (total from breakdown: {total:.2f} ms)", flush=True)
    else:
        print("No compile_timings_ms in response (ensure X-Compile-Timing: 1 and use_dynamic=True).", flush=True)


if __name__ == "__main__":
    main()
