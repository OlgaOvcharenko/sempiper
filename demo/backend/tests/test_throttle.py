"""
Tests for throttling and client-disconnect behavior.

Verifies:
1. The execute SSE generator kills the subprocess when the client disconnects
   (GeneratorExit propagates through the polling loop and proc.kill() is called).
2. No kill is called when the subprocess finishes normally before the generator is closed.
"""

import threading
from unittest.mock import MagicMock

import pytest


def _make_blocking_proc():
    """Mock subprocess that blocks on wait() until kill() is called."""
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = -1
    proc.stdin = MagicMock()

    kill_event = threading.Event()

    def blocking_wait():
        # Block until kill() is signalled (or 5s timeout to prevent hanging tests)
        kill_event.wait(timeout=5.0)
        return -1

    def do_kill():
        kill_event.set()

    proc.wait.side_effect = blocking_wait
    proc.kill.side_effect = do_kill
    proc.stdout.readline.return_value = b""
    return proc


def _make_fast_proc():
    """Mock subprocess that returns immediately (simulates quick successful run)."""
    proc = MagicMock()
    proc.pid = 11111
    proc.returncode = 0
    proc.stdin = MagicMock()
    proc.wait.return_value = 0
    proc.stdout.readline.return_value = b""
    return proc


def _fake_compile_result():
    """Minimal compile result with one input node so the subprocess branch runs."""
    from models.schemas import CompileNode, CompileEdge

    result = MagicMock()
    result.nodes = [CompileNode(id="as_X_1", type="input", label="as_X", source_range=None)]
    result.edges = []
    result.validation_errors = []
    return result


def test_stream_execute_generator_kills_subprocess_on_close(monkeypatch):
    """
    When the SSE generator is closed mid-execution (simulating client disconnect),
    proc.kill() must be called so the subprocess does not become a zombie.
    """
    from services.execute_stream import stream_execute_events

    # Patch compile so we don't need the full skrub environment
    monkeypatch.setattr(
        "services.graph_api.compile_script_to_graph_dynamic",
        lambda code, **kw: _fake_compile_result(),
    )

    proc = _make_blocking_proc()
    monkeypatch.setattr("services.execute_stream.subprocess.Popen", lambda *a, **kw: proc)

    gen = stream_execute_events(
        "x = sempipes.as_X(df, 'X')",
        script_id=None,
        llm_name=None,
        temperature=None,
        cache_key=None,
    )

    # Advance the generator until we receive a b"" heartbeat from the polling loop.
    # The polling loop yields b"" every 0.1s while the subprocess is running.
    got_heartbeat = False
    for _ in range(50):
        try:
            chunk = next(gen)
            if chunk == b"":
                got_heartbeat = True
                break
        except StopIteration:
            break

    assert got_heartbeat, (
        "Generator should yield b'' heartbeat during subprocess polling loop. "
        "If it reached StopIteration first, the subprocess may have exited before we could close."
    )

    # Simulate client disconnect (Starlette calls generator.close() on broken pipe)
    gen.close()

    # The subprocess must be killed
    assert proc.kill.called, "proc.kill() must be called when generator is closed (client disconnect)"


def test_stream_execute_no_kill_when_subprocess_finishes_normally(monkeypatch):
    """
    When the subprocess finishes before the generator is closed (normal case),
    proc.kill() must NOT be called — no unnecessary termination.
    """
    from services.execute_stream import stream_execute_events

    monkeypatch.setattr(
        "services.graph_api.compile_script_to_graph_dynamic",
        lambda code, **kw: _fake_compile_result(),
    )

    proc = _make_fast_proc()
    monkeypatch.setattr("services.execute_stream.subprocess.Popen", lambda *a, **kw: proc)

    gen = stream_execute_events(
        "x = sempipes.as_X(df, 'X')",
        script_id=None,
        llm_name=None,
        temperature=None,
        cache_key=None,
    )

    # Exhaust the generator fully (subprocess finishes immediately)
    list(gen)

    # proc.kill() should NOT have been called in the normal-completion path
    assert not proc.kill.called, "proc.kill() must not be called when subprocess finishes normally"
