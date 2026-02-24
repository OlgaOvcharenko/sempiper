"""
Fuzzing tests for /api/compile and /api/execute with bad, weird, and adversarial scripts.

Goals:
- /api/compile NEVER crashes (always 200 with valid JSON shape).
- /api/execute ALWAYS terminates (always ends with a 'done' or 'error' SSE event).
- proc.kill() is always called on GeneratorExit regardless of script content.

Test infrastructure:
- conftest.py autouse fixtures handle litellm mocking and skrub_graph_runner Popen mocking.
- Individual test classes override Popen for specific failure scenarios using monkeypatch.
- time.sleep is patched to a no-op in execute tests to keep total runtime under 10s.
"""

import json
import random
import string
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Script corpus
# ---------------------------------------------------------------------------

_SYNTAX_ERROR_SCRIPTS = [
    ("missing_colon", "if True\n    x = 1"),
    ("unclosed_bracket", "x = [1, 2, 3\nprint(x)"),
    ("unclosed_string", 'x = "hello\nprint(x)'),
    ("invalid_indent", "def foo():\nx = 1"),
    ("double_star_invalid", "x = **{}"),
    ("bare_return", "return 42"),
]

_RUNTIME_ERROR_SCRIPTS = [
    ("name_error", "x = undefined_variable_fuzz_xyz"),
    ("zero_division", "x = 1 / 0"),
    ("type_error", "x = len(123)"),
    ("attribute_error", "x = None.no_such_method()"),
    ("import_nonexistent", "import this_module_does_not_exist_fuzz"),
    ("index_error", "x = [][0]"),
]

_STRUCTURAL_ODDITY_SCRIPTS = [
    ("empty_string", ""),
    ("whitespace_only", "   \n\t\n  "),
    ("only_comment", "# just a comment\n# another comment"),
    ("very_long_script", "x = 1\n" * 5000),
    ("unicode_in_string", 'x = "héllo — 日本語 🎉"\nprint(x)'),
    ("null_bytes", "x = 1\x00\nprint(x)"),
]

_DANGEROUS_SCRIPTS = [
    ("os_system", "import os\nos.system('echo FUZZ')"),
    ("subprocess_call", "import subprocess\nsubprocess.run(['echo', 'FUZZ'])"),
    ("exec_call", "exec(\"import os; os.system('echo X')\")"),
    ("open_etc_passwd", "with open('/etc/passwd') as f: data = f.read()"),
]

_SEMI_VALID_SCRIPTS = [
    ("pure_python_math", "x = 1 + 2\ny = x * 3\nprint(y)"),
    ("imports_only", "import os\nimport json\nimport re"),
    ("class_def", "class Foo:\n    def bar(self):\n        return 42"),
    ("function_def", "def my_func(x):\n    return x * 2\nresult = my_func(5)"),
]

_GOOD_SCRIPTS = [
    ("minimal_as_x", 'basket_ids = sempipes.as_X(baskets[["ID"]], "X")'),
    (
        "as_x_sem_fillna",
        'basket_ids = sempipes.as_X(baskets[["ID"]], "X")\n'
        'products = products.sem_fillna(target_column="make")',
    ),
    (
        "full_pipeline_static",
        'basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")\n'
        'fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")\n'
        'products = products.sem_fillna(target_column="make")\n'
        "result = basket_ids.skb.eval()",
    ),
]

_ALL_BAD_SCRIPTS = (
    _SYNTAX_ERROR_SCRIPTS
    + _RUNTIME_ERROR_SCRIPTS
    + _STRUCTURAL_ODDITY_SCRIPTS
    + _DANGEROUS_SCRIPTS
    + _SEMI_VALID_SCRIPTS
)  # 26 entries

_ALL_SCRIPTS = _ALL_BAD_SCRIPTS + _GOOD_SCRIPTS  # 29 entries


# ---------------------------------------------------------------------------
# Property-based random script generator (fixed seed for reproducibility)
# ---------------------------------------------------------------------------

def _make_random_scripts(seed: int = 42, count: int = 20) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    scripts = []
    _keywords = [
        "import", "def", "class", "if", "for", "while", "return",
        "sempipes", "skrub", "as_X", "sem_fillna", "x", "y", "=", "(", ")",
    ]
    for i in range(count):
        kind = rng.choice(["random_ascii", "random_python_like", "random_unicode"])
        if kind == "random_ascii":
            length = rng.randint(0, 500)
            script = "".join(rng.choices(string.printable, k=length))
        elif kind == "random_python_like":
            length = rng.randint(1, 30)
            script = " ".join(rng.choices(_keywords, k=length))
        else:
            # Exclude surrogate range U+D800–U+DFFF (not valid in JSON/UTF-8)
            def _rand_char(r: random.Random) -> str:
                cp = r.randint(0x20, 0xFFFF - 0x800)  # shift range to exclude surrogates
                if cp >= 0xD800:
                    cp += 0x800  # skip over D800-DFFF
                return chr(cp)

            chars = [_rand_char(rng) for _ in range(rng.randint(10, 200))]
            script = "".join(chars)
        scripts.append((f"random_{kind}_{i}", script))
    return scripts


_RANDOM_SCRIPTS = _make_random_scripts()


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE 'data: {...}' lines into a list of dicts. Skips malformed lines."""
    events = []
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _last_terminating_event(events: list[dict]) -> dict | None:
    """Return the last 'done' or 'error' event, or None."""
    for ev in reversed(events):
        if ev.get("type") in ("done", "error"):
            return ev
    return None


# ---------------------------------------------------------------------------
# Class 1: Compile endpoint fuzz
# ---------------------------------------------------------------------------

class TestCompileFuzz:
    """POST /api/compile never crashes on any input (use_dynamic=False for speed)."""

    @pytest.mark.parametrize("name,script", _ALL_SCRIPTS, ids=[n for n, _ in _ALL_SCRIPTS])
    def test_compile_always_200_with_valid_shape(self, name, script):
        """Every script returns 200 with nodes/edges/validation_errors as lists."""
        resp = client.post(
            "/api/compile",
            json={"input_code": script, "use_dynamic": False},
        )
        assert resp.status_code == 200, (
            f"[{name}] Expected 200, got {resp.status_code}: {resp.text[:300]}"
        )
        data = resp.json()
        assert "nodes" in data, f"[{name}] Response missing 'nodes'"
        assert "edges" in data, f"[{name}] Response missing 'edges'"
        assert "validation_errors" in data, f"[{name}] Response missing 'validation_errors'"
        assert isinstance(data["nodes"], list), f"[{name}] 'nodes' must be a list"
        assert isinstance(data["edges"], list), f"[{name}] 'edges' must be a list"
        assert isinstance(data["validation_errors"], list), (
            f"[{name}] 'validation_errors' must always be a list"
        )
        assert "Traceback (most recent call last)" not in resp.text, (
            f"[{name}] Response must not contain a Python traceback"
        )

    @pytest.mark.parametrize("name,script", _GOOD_SCRIPTS, ids=[n for n, _ in _GOOD_SCRIPTS])
    def test_good_scripts_produce_nodes(self, name, script):
        """Good sempipes scripts must produce at least one node via static parse."""
        resp = client.post(
            "/api/compile",
            json={"input_code": script, "use_dynamic": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) >= 1, (
            f"[{name}] Good script should produce nodes. Got: {data}"
        )

    @pytest.mark.parametrize(
        "name,script",
        _SYNTAX_ERROR_SCRIPTS + _RUNTIME_ERROR_SCRIPTS,
        ids=[n for n, _ in _SYNTAX_ERROR_SCRIPTS + _RUNTIME_ERROR_SCRIPTS],
    )
    def test_bad_scripts_produce_empty_nodes(self, name, script):
        """Bad scripts (no sempipes operators) produce empty nodes list from static parse."""
        resp = client.post(
            "/api/compile",
            json={"input_code": script, "use_dynamic": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Static parser is regex-based: no sempipes operators → no nodes
        assert data["nodes"] == [], (
            f"[{name}] Bad script should yield no nodes via static parse. Got: {data['nodes']}"
        )
        assert isinstance(data["validation_errors"], list)


# ---------------------------------------------------------------------------
# Class 2: Execute endpoint fuzz (with subprocess mocked by conftest autouse)
# ---------------------------------------------------------------------------

class TestExecuteFuzz:
    """POST /api/execute always terminates cleanly with 'done' or 'error' SSE event."""

    @pytest.fixture(autouse=True)
    def _fast_sleep(self, monkeypatch):
        """Patch time.sleep in execute_stream to a no-op so tests stay fast."""
        monkeypatch.setattr("services.execute_stream.time.sleep", lambda _: None)

    @pytest.mark.parametrize("name,script", _ALL_SCRIPTS, ids=[n for n, _ in _ALL_SCRIPTS])
    def test_execute_always_terminates_with_done_or_error(self, name, script):
        """Every script must end the SSE stream with a 'done' or 'error' event."""
        resp = client.post("/api/execute", json={"input_code": script})
        assert resp.status_code == 200, (
            f"[{name}] Expected 200 SSE stream, got {resp.status_code}: {resp.text[:300]}"
        )
        assert "text/event-stream" in resp.headers.get("content-type", ""), (
            f"[{name}] Expected text/event-stream content-type"
        )
        events = _parse_sse_events(resp.text)
        terminator = _last_terminating_event(events)
        assert terminator is not None, (
            f"[{name}] Stream must end with 'done' or 'error'. "
            f"Got event types: {[e.get('type') for e in events]}"
        )
        assert terminator["type"] in ("done", "error"), (
            f"[{name}] Terminating event must be 'done' or 'error', got: {terminator}"
        )

    @pytest.mark.parametrize("name,script", _ALL_SCRIPTS, ids=[n for n, _ in _ALL_SCRIPTS])
    def test_execute_no_unhandled_exception_in_response(self, name, script):
        """The response must never be a 500 JSON error or contain a raw traceback."""
        resp = client.post("/api/execute", json={"input_code": script})
        assert resp.status_code != 500, (
            f"[{name}] Got 500 Internal Server Error: {resp.text[:300]}"
        )
        assert "Traceback (most recent call last)" not in resp.text, (
            f"[{name}] Response body contains Python traceback (unhandled exception)"
        )


# ---------------------------------------------------------------------------
# Class 3: Execute fuzz with subprocess failures
# ---------------------------------------------------------------------------

class TestExecuteSubprocessFailFuzz:
    """
    Override the autouse Popen mock to simulate subprocess failures.
    Assert the SSE stream always terminates gracefully regardless.
    """

    @pytest.fixture(autouse=True)
    def _fast_sleep(self, monkeypatch):
        monkeypatch.setattr("services.execute_stream.time.sleep", lambda _: None)

    @staticmethod
    def _make_crash_proc() -> MagicMock:
        """Subprocess that exits immediately with non-zero returncode and empty stdout."""
        proc = MagicMock()
        proc.pid = 42001
        proc.stdin = MagicMock()
        proc.stdout.readline.return_value = b""
        proc.wait.return_value = 1
        proc.returncode = 1
        return proc

    @staticmethod
    def _make_garbage_stdout_proc() -> MagicMock:
        """Subprocess that writes malformed (non-JSON) content after the marker."""
        proc = MagicMock()
        proc.pid = 42002
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [
            b"##SEMPIPES_NODE_CODE##\n",
            b"THIS IS NOT JSON AT ALL\n",
            b"##END##\n",
            b"<not-an-svg>random garbage\xff\xfe",
            b"",
        ]
        proc.wait.return_value = 0
        proc.returncode = 0
        return proc

    @staticmethod
    def _make_nonzero_garbage_proc() -> MagicMock:
        """Subprocess that writes a traceback to stdout and exits non-zero."""
        proc = MagicMock()
        proc.pid = 42003
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [
            b"Traceback (most recent call last):\n",
            b"  File 'script.py', line 1, in <module>\n",
            b"RuntimeError: pipeline exploded\n",
            b"",
        ]
        proc.wait.return_value = 2
        proc.returncode = 2
        return proc

    @pytest.mark.parametrize(
        "name,script",
        _ALL_BAD_SCRIPTS[:6],
        ids=[n for n, _ in _ALL_BAD_SCRIPTS[:6]],
    )
    def test_subprocess_crash_terminates_gracefully(self, name, script):
        """Non-zero returncode + empty stdout always ends stream with 'done'."""
        proc = self._make_crash_proc()
        with patch("services.execute_stream.subprocess.Popen", lambda *a, **kw: proc):
            resp = client.post("/api/execute", json={"input_code": script})
        assert resp.status_code == 200, (
            f"[{name}] Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = _parse_sse_events(resp.text)
        types = [e.get("type") for e in events]
        assert "done" in types, (
            f"[{name}] Stream must contain 'done' even on subprocess crash. Got: {types}"
        )

    @pytest.mark.parametrize(
        "name,script",
        _ALL_BAD_SCRIPTS[:6],
        ids=[n for n, _ in _ALL_BAD_SCRIPTS[:6]],
    )
    def test_garbage_stdout_terminates_gracefully(self, name, script):
        """Malformed subprocess stdout does not crash the stream."""
        proc = self._make_garbage_stdout_proc()
        with patch("services.execute_stream.subprocess.Popen", lambda *a, **kw: proc):
            resp = client.post("/api/execute", json={"input_code": script})
        assert resp.status_code == 200, (
            f"[{name}] Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = _parse_sse_events(resp.text)
        terminator = _last_terminating_event(events)
        assert terminator is not None, (
            f"[{name}] Stream must end with 'done' or 'error'. "
            f"Got: {[e.get('type') for e in events]}"
        )

    @pytest.mark.parametrize(
        "name,script",
        _SYNTAX_ERROR_SCRIPTS[:3],
        ids=[n for n, _ in _SYNTAX_ERROR_SCRIPTS[:3]],
    )
    def test_nonzero_garbage_stdout_terminates_gracefully(self, name, script):
        """Subprocess crash with traceback in stdout produces 'error' + 'done'."""
        proc = self._make_nonzero_garbage_proc()
        with patch("services.execute_stream.subprocess.Popen", lambda *a, **kw: proc):
            resp = client.post("/api/execute", json={"input_code": script})
        assert resp.status_code == 200, (
            f"[{name}] Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = _parse_sse_events(resp.text)
        types = [e.get("type") for e in events]
        assert "done" in types, f"[{name}] Stream must always end with 'done'. Got: {types}"
        assert "error" in types, (
            f"[{name}] Non-zero returncode must produce 'error' event. Got: {types}"
        )


# ---------------------------------------------------------------------------
# Class 4: Throttle fuzz — proc.kill() always called on disconnect
# ---------------------------------------------------------------------------

class TestExecuteThrottleFuzz:
    """
    proc.kill() is always called on generator close (client disconnect),
    regardless of the script content. Directly uses stream_execute_events().
    """

    @staticmethod
    def _make_blocking_proc() -> MagicMock:
        """Blocking proc: wait() blocks until kill() is called (mirrors test_throttle.py)."""
        proc = MagicMock()
        proc.pid = 88888
        proc.returncode = -1
        proc.stdin = MagicMock()
        kill_event = threading.Event()

        def blocking_wait():
            kill_event.wait(timeout=5.0)
            return -1

        def do_kill():
            kill_event.set()

        proc.wait.side_effect = blocking_wait
        proc.kill.side_effect = do_kill
        proc.stdout.readline.return_value = b""
        return proc

    @staticmethod
    def _fake_compile_result():
        """Minimal compile result with one input node so the subprocess branch runs."""
        from models.schemas import CompileNode

        result = MagicMock()
        result.nodes = [
            CompileNode(id="as_X_1", type="input", label="as_X", source_range=None)
        ]
        result.edges = []
        result.validation_errors = []
        return result

    @pytest.mark.parametrize(
        "name,script",
        [
            ("syntax_error", "if True\n    x = 1"),
            ("empty_script", ""),
            ("runtime_error", "x = 1 / 0"),
            ("unicode_script", 'x = "日本語"\nprint(x)'),
            ("null_bytes", "x = 1\x00"),
            ("very_long", "x = 1\n" * 200),
        ],
        ids=["syntax_error", "empty_script", "runtime_error", "unicode_script", "null_bytes", "very_long"],
    )
    def test_kill_called_on_disconnect_for_bad_scripts(self, monkeypatch, name, script):
        """
        proc.kill() must be called when the generator is closed mid-execution,
        regardless of script content.
        """
        from services.execute_stream import stream_execute_events

        monkeypatch.setattr(
            "services.graph_api.compile_script_to_graph_dynamic",
            lambda code, **kw: self._fake_compile_result(),
        )
        proc = self._make_blocking_proc()
        monkeypatch.setattr(
            "services.execute_stream.subprocess.Popen",
            lambda *a, **kw: proc,
        )

        gen = stream_execute_events(
            script,
            script_id=None,
            llm_name=None,
            temperature=None,
            cache_key=None,
        )

        # Advance until b"" heartbeat (polling loop is running) or generator exhausts.
        got_heartbeat = False
        for _ in range(50):
            try:
                chunk = next(gen)
                if chunk == b"":
                    got_heartbeat = True
                    break
            except StopIteration:
                break

        if not got_heartbeat:
            # Generator finished before we could close it (e.g., empty script has no nodes
            # and skips the subprocess branch entirely). Normal completion — no kill needed.
            assert not proc.kill.called, (
                f"[{name}] proc.kill() should not be called when generator finishes naturally"
            )
            return

        # Simulate client disconnect
        gen.close()

        assert proc.kill.called, (
            f"[{name}] proc.kill() must be called when generator is closed (client disconnect)"
        )


# ---------------------------------------------------------------------------
# Class 5: Property-based fuzz (random scripts against compile endpoint)
# ---------------------------------------------------------------------------

class TestPropertyBasedFuzz:
    """Compile never crashes on random string inputs (fixed seed for reproducibility)."""

    @pytest.mark.parametrize("name,script", _RANDOM_SCRIPTS, ids=[n for n, _ in _RANDOM_SCRIPTS])
    def test_random_script_compile_always_200(self, name, script):
        """Random scripts must never crash /api/compile."""
        resp = client.post(
            "/api/compile",
            json={"input_code": script, "use_dynamic": False},
        )
        assert resp.status_code == 200, (
            f"[{name}] Compile crashed on random script: {resp.status_code} {resp.text[:200]}"
        )
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert "validation_errors" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)
        assert isinstance(data["validation_errors"], list)
