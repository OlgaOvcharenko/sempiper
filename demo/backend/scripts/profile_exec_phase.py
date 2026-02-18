#!/usr/bin/env python
"""
Profile which parts of the exec() phase use time when running the rewritten simple script.

Run from repo root:
  poetry run python demo/backend/scripts/profile_exec_phase.py [simple|medium|full]

Uses cProfile on exec(rewritten, exec_globals) and prints top functions by cumulative time.
"""
from __future__ import annotations

import cProfile
import io
import pstats
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

_repo_root = _backend.parent.parent
_scripts_dir = _repo_root / "pipeline_scripts"


def load_script(name: str) -> str:
    import json
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
    print(f"Profiling exec phase for script: {name} ({len(script)} chars)", flush=True)

    from services.graph_api import (
        rewrite_script_for_graph_extraction,
        _graph_extraction_mock_completion,
        _graph_extraction_mock_batch_completion,
    )

    rewritten = rewrite_script_for_graph_extraction(script)
    print("Rewritten script (first 500 chars):", flush=True)
    print(rewritten[:500], flush=True)
    print("---", flush=True)

    # Patch sempipes.llm.llm so exec() does not call real LLM (same as extract_skrub_graph)
    llm_module = None
    try:
        import sempipes.llm.llm as llm_module
    except ImportError:
        pass
    orig_completion = None
    orig_batch = None
    if llm_module is not None:
        orig_completion = llm_module.completion
        orig_batch = getattr(llm_module, "batch_completion", None)
        llm_module.completion = _graph_extraction_mock_completion
        llm_module.batch_completion = _graph_extraction_mock_batch_completion

    # Build exec_globals the same way as extract_skrub_graph
    exec_globals: dict = {"__builtins__": __builtins__}
    try:
        import skrub
        exec_globals["skrub"] = skrub
    except ImportError as e:
        raise SystemExit(f"skrub not available: {e}") from e
    try:
        import sempipes
        exec_globals["sempipes"] = sempipes
    except ImportError:
        pass
    try:
        from sempipes import sem_choose
        exec_globals["sem_choose"] = sem_choose
    except ImportError:
        pass
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        exec_globals["HistGradientBoostingClassifier"] = HistGradientBoostingClassifier
    except ImportError:
        pass
    try:
        from sklearn.linear_model import LinearRegression
        exec_globals["LinearRegression"] = LinearRegression
    except ImportError:
        pass
    try:
        from catboost import CatBoostClassifier
        exec_globals["CatBoostClassifier"] = CatBoostClassifier
    except ImportError:
        pass

    prof = cProfile.Profile()
    prof.enable()
    try:
        exec(rewritten, exec_globals)
    finally:
        if llm_module is not None:
            llm_module.completion = orig_completion
            if orig_batch is not None:
                llm_module.batch_completion = orig_batch
    prof.disable()

    stream = io.StringIO()
    ps = pstats.Stats(prof, stream=stream).sort_stats(pstats.SortKey.CUMULATIVE)
    ps.print_stats(40)
    print(stream.getvalue(), flush=True)

    print("\nBy total time (top 30):", flush=True)
    stream2 = io.StringIO()
    ps2 = pstats.Stats(prof, stream=stream2).sort_stats("time")
    ps2.print_stats(30)
    print(stream2.getvalue(), flush=True)


if __name__ == "__main__":
    main()
