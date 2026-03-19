"""
Pytest configuration and fixtures for the demo backend.

Test strategy: keep tests close to sempipes (e.g. call sempipes code paths)
but NEVER call real LLMs. We simulate correct behaviour via mocks so tests
run fast and without API keys or network.

- This conftest patches litellm.completion / batch_completion when available
  so any code path that reaches litellm gets a fake response.
- Tests that invoke the execute stream (POST /api/execute) explicitly mock
  the code-generation entry point so we never call sempipes LLM; see
  test_codegen.py (patch of execute_stream._generate_code_via_sempipes).
- Tests that use sempipes code generation directly (e.g. test_sempipes_code_
  generation_uses_mock_no_llm_call) patch sempipes.llm.llm._generate_code_
  from_messages so the LLM returns fixed code without hitting the network.
"""

import pytest

# Test files that are slow (compile real pipelines, download data, fuzz, etc.).
# These are skipped by the default fast run (addopts = -m "not slow" in pytest.ini).
# Run with: pytest -m slow   to execute them explicitly.
_SLOW_TEST_FILES = {
    "test_all_pipeline_scripts_source_ranges.py",
    "test_compilation_error_handling.py",
    "test_compile_as_x_edges.py",
    "test_compile_graph_single_sink.py",
    "test_compile_sem_choose.py",
    "test_compile_source_ranges.py",
    "test_data_summary.py",
    "test_data_summary_direct.py",
    "test_fuzz_bad_scripts.py",
    "test_getitem_column_ranges.py",
    "test_getitem_mapping.py",
    "test_graph_api.py",
    "test_graph_edges.py",
    "test_graph_fusion.py",
    "test_graph_parity.py",
    "test_graph_structure.py",
    "test_house_prices_museums_compile.py",
    "test_intermediate_previews.py",
    "test_medium_exact_positions.py",
    "test_medium_script_debug.py",
    "test_medium_script_source_ranges.py",
    "test_medium_script_static_parse.py",
    "test_new_scripts_graph_connectivity.py",
    "test_new_scripts_source_ranges.py",
    "test_optimise_colopro_parsing.py",
    "test_pandas_operations.py",
    "test_source_range_permutations.py",
    "test_syntax_variations.py",
}


def pytest_collection_modifyitems(items):
    """Auto-mark tests in slow files with pytest.mark.slow."""
    slow_mark = pytest.mark.slow
    for item in items:
        if item.fspath.basename in _SLOW_TEST_FILES:
            item.add_marker(slow_mark)


def _mock_completion(*args, **kwargs):
    """Fake litellm.completion response so no real LLM is called."""

    class Choice:
        class Message:
            content = "def __mock__(): pass"

        message = Message()

    class Response:
        choices = [Choice()]

    return Response()


def _mock_batch_completion(*args, messages=None, **kwargs):
    """Fake litellm.batch_completion response so no real LLM is called."""
    n = len(messages) if messages else 1

    class Choice:
        class Message:
            content = "{}"

        message = Message()

    return [type("Response", (), {"choices": [Choice()]})() for _ in range(n)]


@pytest.fixture(autouse=True)
def mock_litellm_if_available(monkeypatch):
    """
    If litellm is importable, patch completion and batch_completion so no
    real LLM is called. Tests that use sempipes code generation should also
    patch sempipes.llm.llm._generate_code_from_messages (see test_codegen).
    """
    try:
        import litellm

        monkeypatch.setattr(litellm, "completion", _mock_completion)
        monkeypatch.setattr(litellm, "batch_completion", _mock_batch_completion)
    except ImportError:
        pass
    yield


def _make_runner_readline_for_code(pipeline_code: str):
    """
    Return a callable usable as proc.stdout.readline.side_effect that emits
    ##SEMPIPES_NODE_CODE## blocks with skrub_node_ids matching the actual compile
    IDs for the given pipeline code.  Called lazily so that stdin has already
    been written before readline is first invoked.
    """
    import json

    def _build_lines() -> list[bytes]:
        try:
            from services.graph_api import compile_script_to_graph_dynamic
            from services.execute_stream import _is_semantic_operator
            result = compile_script_to_graph_dynamic(pipeline_code)
            sem_ids = [n.id for n in result.nodes if _is_semantic_operator(n.label)]
        except Exception:
            sem_ids = ["1"]  # safe fallback for trivial single-operator pipelines

        lines: list[bytes] = []
        for i, node_id in enumerate(sem_ids):
            code_text = (
                "# Simulated sempipes code (no real LLM call)\nresult = process(data)"
                if i == 0 else f"# mock op {i}\npass"
            )
            lines.append(b"##SEMPIPES_NODE_CODE##\n")
            lines.append(
                (json.dumps({"index": i, "code": code_text, "skrub_node_id": node_id}) + "\n").encode("utf-8")
            )
            lines.append(b"##END##\n")
        lines.append(b"")  # readline returns b"" → reader thread stops
        return lines

    _iter: list | None = None

    def readline():
        nonlocal _iter
        if _iter is None:
            _iter = _build_lines()
        if not _iter:
            return b""
        return _iter.pop(0)

    return readline


@pytest.fixture(autouse=True)
def mock_skrub_graph_runner(monkeypatch):
    """
    Patch subprocess.Popen in execute_stream so we never run the real
    skrub_graph_runner subprocess. Default stdout includes ##SEMPIPES_NODE_CODE##
    blocks with correct skrub_node_ids derived by compiling the pipeline code
    that was written to stdin — so operator nodes always get mock code regardless
    of pipeline complexity.

    NOTE: Only mocks calls that include 'skrub_graph_runner' in the command.
    Other subprocess calls (like data summary extraction) use real subprocess.
    """
    from unittest.mock import MagicMock
    import subprocess

    # Save reference to real Popen BEFORE any patching
    _real_popen = subprocess.Popen

    def _fake_popen(*args, **kwargs):
        # Check if this is a skrub_graph_runner call
        # skrub_graph_runner calls use: [sys.executable, "-m", "services.skrub_graph_runner"]
        is_graph_runner = False
        if args and len(args) > 0:
            cmd = args[0]
            if isinstance(cmd, list) and len(cmd) >= 3:
                if "skrub_graph_runner" in " ".join(cmd):
                    is_graph_runner = True

        # If not a graph runner call, use real subprocess
        if not is_graph_runner:
            return _real_popen(*args, **kwargs)

        # Mock graph runner calls: capture stdin to determine correct skrub_node_ids.
        # Uses a threading.Event so readline (called from reader thread) waits until
        # stdin has been fully written by the main thread.
        import threading
        proc = MagicMock()
        captured_stdin: list[str] = []
        stdin_closed = threading.Event()

        def _stdin_write(data: bytes | str) -> None:
            captured_stdin.append(data.decode("utf-8") if isinstance(data, bytes) else data)

        def _stdin_close() -> None:
            stdin_closed.set()

        proc.stdin.write.side_effect = _stdin_write
        proc.stdin.close = _stdin_close

        _readline_state: dict = {"fn": None}

        def _readline():
            stdin_closed.wait(timeout=5.0)  # wait for main thread to finish writing stdin
            if _readline_state["fn"] is None:
                pipeline_code = "".join(captured_stdin)
                _readline_state["fn"] = _make_runner_readline_for_code(pipeline_code)
            return _readline_state["fn"]()

        proc.stdout.readline = _readline
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)
    yield
