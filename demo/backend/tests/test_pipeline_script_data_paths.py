"""
Tests that pipeline scripts with local data files (house_prices, museums) can
resolve their data paths correctly when run via the demo runner.

Covers two mechanisms:
1. execute_stream sets SEMPIPES_SCRIPT_PATH env var when script_id is known
2. skrub_graph_runner sets __file__ from SEMPIPES_SCRIPT_PATH so scripts can
   resolve relative data paths via os.path.dirname(__file__)
"""

import os
import json
import pytest

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(os.path.dirname(_BACKEND_ROOT))
_PIPELINE_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "pipeline_scripts")
_MANIFEST_PATH = os.path.join(_PIPELINE_SCRIPTS_DIR, "manifest.json")


def _manifest_entries():
    if not os.path.isfile(_MANIFEST_PATH):
        return []
    with open(_MANIFEST_PATH) as f:
        return json.load(f)


def _script_path_for_id(script_id: str) -> str | None:
    """Resolve the actual .py file path for a given script_id via manifest."""
    for entry in _manifest_entries():
        if entry.get("id") == script_id:
            return os.path.join(_PIPELINE_SCRIPTS_DIR, entry["file"])
    return None


# ------------------------------------------------------------------ #
# Test 1: SEMPIPES_SCRIPT_PATH resolves to an existing file for known scripts
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("script_id", ["house", "museum"])
def test_script_path_resolves_for_known_scripts(script_id):
    """For manifest-listed scripts that load local data, SEMPIPES_SCRIPT_PATH must resolve to an existing .py file."""
    path = _script_path_for_id(script_id)
    assert path is not None, f"script_id '{script_id}' not found in manifest"
    assert os.path.isfile(path), (
        f"Script file not found: {path}\n"
        f"Check that '{script_id}' entry in manifest.json points to an existing file."
    )


# ------------------------------------------------------------------ #
# Test 2: Data files referenced by house_prices.py exist relative to __file__
# ------------------------------------------------------------------ #

def test_house_prices_data_files_exist():
    """house_prices.py loads CSVs relative to __file__; verify all three data files exist."""
    script_path = _script_path_for_id("house")
    if script_path is None:
        pytest.skip("house script not in manifest")
    if not os.path.isfile(script_path):
        pytest.skip(f"house_prices.py not found at {script_path}")

    data_dir = os.path.join(os.path.dirname(script_path), "house_prices_normalized")
    missing = []
    for fname in ("fact_houses.csv", "dim_cities.csv", "dim_images.csv"):
        p = os.path.join(data_dir, fname)
        if not os.path.isfile(p):
            missing.append(p)
    assert not missing, (
        f"house_prices data files missing:\n" + "\n".join(missing) +
        f"\nExpected in: {data_dir}"
    )


# ------------------------------------------------------------------ #
# Test 3: museums.py data file exists relative to __file__
# ------------------------------------------------------------------ #

def test_museums_data_file_exists():
    """museums.py loads met_10k.csv relative to __file__; verify it exists."""
    script_path = _script_path_for_id("museum")
    if script_path is None:
        pytest.skip("museum script not in manifest")
    if not os.path.isfile(script_path):
        pytest.skip(f"museums.py not found at {script_path}")

    data_path = os.path.join(os.path.dirname(script_path), "met_10k.csv")
    assert os.path.isfile(data_path), (
        f"museums data file missing: {data_path}"
    )


# ------------------------------------------------------------------ #
# Test 4: runner _prepare_globals() sets __file__ from SEMPIPES_SCRIPT_PATH
# ------------------------------------------------------------------ #

def test_runner_prepare_globals_sets_dunder_file(monkeypatch):
    """_prepare_globals() must set __file__ from SEMPIPES_SCRIPT_PATH env var."""
    import services.skrub_graph_runner as runner

    fake_path = "/some/pipeline_scripts/house_prices.py"
    monkeypatch.setenv("SEMPIPES_SCRIPT_PATH", fake_path)
    g = runner._prepare_globals()
    assert g.get("__file__") == fake_path, (
        f"Expected __file__ == {fake_path!r}, got {g.get('__file__')!r}"
    )


def test_runner_prepare_globals_file_empty_when_no_env(monkeypatch):
    """Without SEMPIPES_SCRIPT_PATH, __file__ is set to empty string (not missing)."""
    import services.skrub_graph_runner as runner

    monkeypatch.delenv("SEMPIPES_SCRIPT_PATH", raising=False)
    g = runner._prepare_globals()
    assert "__file__" in g, "__file__ key must always be present in exec globals"
    assert g["__file__"] == "", (
        f"Expected empty string when env var absent, got {g['__file__']!r}"
    )


# ------------------------------------------------------------------ #
# Test 5: execute_stream sets SEMPIPES_SCRIPT_PATH in subprocess env
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("script_id,expected_file", [
    ("house", "house_prices.py"),
    ("museum", "museums.py"),
])
def test_execute_stream_subprocess_env_has_script_path(script_id, expected_file, monkeypatch):
    """stream_execute_events must set SEMPIPES_SCRIPT_PATH in subprocess_env for known scripts."""
    captured_env = {}

    def _fake_popen(cmd, stdin, stdout, stderr, cwd, env, text):
        captured_env.update(env or {})
        raise RuntimeError("stop after env capture")

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)
    # Also stub compile so we don't hit the real compiler
    monkeypatch.setattr(
        "services.graph_api.compile_script_to_graph_dynamic",
        lambda script: _make_minimal_compile_result(),
    )

    from services.execute_stream import stream_execute_events
    # Drain the generator; it will raise RuntimeError inside but we catch events before that
    try:
        list(stream_execute_events("x = 1", script_id=script_id, cache_key=None, temperature=0.0, llm_name="gpt-4o"))
    except Exception:
        pass

    script_path = captured_env.get("SEMPIPES_SCRIPT_PATH", "")
    assert script_path, (
        f"SEMPIPES_SCRIPT_PATH not set in subprocess env for script_id={script_id!r}"
    )
    assert script_path.endswith(expected_file), (
        f"Expected SEMPIPES_SCRIPT_PATH to end with {expected_file!r}, got {script_path!r}"
    )
    assert os.path.isfile(script_path), (
        f"SEMPIPES_SCRIPT_PATH points to non-existent file: {script_path}"
    )


def _make_minimal_compile_result():
    from unittest.mock import MagicMock
    result = MagicMock()
    result.nodes = []
    result.edges = []
    return result
