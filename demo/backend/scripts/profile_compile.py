#!/usr/bin/env python
"""
One-off script to profile dynamic compile. Run from repo root:
  poetry run python demo/backend/scripts/profile_compile.py [simple|medium|full]
Or from demo/backend:
  poetry run python scripts/profile_compile.py [simple|medium|full]

Prints timing breakdown (extract_ms, fuse_ms, static_ms, merge_ms and
extract sub-phases). Use with cProfile to get full hotspot data:
  poetry run python -m cProfile -s cumtime demo/backend/scripts/profile_compile.py simple
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path so we can import services
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# Repo root = backend -> demo -> repo
_repo_root = _backend.parent.parent
_scripts_dir = _repo_root / "pipeline_scripts"


def load_script(name: str) -> str:
    manifest_path = _scripts_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"No manifest at {manifest_path}")
    import json
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
    print(f"Profiling dynamic compile for script: {name} ({len(script)} chars)", flush=True)

    from services.graph_api import compile_script_to_graph_dynamic

    timings: dict[str, float] = {}
    result = compile_script_to_graph_dynamic(script, timings_out=timings)

    print(f"Nodes: {len(result.nodes)}, Edges: {len(result.edges)}", flush=True)
    print("Timings (ms):", flush=True)
    for k, v in sorted(timings.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k}: {v:.2f}", flush=True)


if __name__ == "__main__":
    main()
