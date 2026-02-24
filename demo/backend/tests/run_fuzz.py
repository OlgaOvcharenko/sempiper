"""
Extended fuzzing runner: hammers /api/compile and /api/execute with random scripts
for a fixed duration, reporting any invariant violations.

Run from demo/backend/:
  poetry run python tests/run_fuzz.py [duration_seconds]
"""
import json
import os
import random
import string
import sys
import time
from unittest.mock import MagicMock, patch

# Patch litellm before importing the app
try:
    import litellm

    litellm.completion = lambda *a, **kw: None
    litellm.batch_completion = lambda *a, **kw: []
except ImportError:
    pass

from fastapi.testclient import TestClient

from main import app

POPEN_TARGET = "services.execute_stream.subprocess.Popen"
SLEEP_TARGET = "services.execute_stream.time.sleep"

client = TestClient(app)

# ---------------------------------------------------------------------------
# Random script generators
# ---------------------------------------------------------------------------

_KEYWORDS = [
    "import", "def", "class", "if", "for", "while", "return",
    "sempipes", "skrub", "as_X", "as_y", "sem_fillna", "sem_gen_features",
    "x", "y", "df", "baskets", "=", "(", ")", "[", "]", ":", ".",
]

_HAND_CORPUS = [
    "",
    "   \n\t\n  ",
    "# just a comment",
    "return 42",
    "x = **{}",
    "if True\n    x = 1",
    "x = [1, 2, 3\nprint(x)",
    'x = "hello\nprint(x)',
    "x = undefined_variable_fuzz_xyz",
    "x = 1 / 0",
    "x = [][0]",
    "import this_module_does_not_exist_fuzz",
    "import os\nos.system('echo FUZZ')",
    "exec(\"import os; os.system('echo X')\")",
    "x = 1\x00\nprint(x)",
    'basket_ids = sempipes.as_X(baskets[["ID"]], "X")',
    'basket_ids = sempipes.as_X(baskets[["ID"]], "X")\n'
    'products = products.sem_fillna(target_column="make")',
    "x = 1 + 2\ny = x * 3\nprint(y)",
]


def _safe_unicode_char(rng: random.Random) -> str:
    """Random unicode char excluding surrogates (U+D800–U+DFFF)."""
    cp = rng.randint(0x20, 0xFFFF - 0x800)
    if cp >= 0xD800:
        cp += 0x800
    return chr(cp)


def rand_script(rng: random.Random) -> str:
    strategy = rng.choice(["corpus", "ascii", "python_like", "unicode", "mixed", "long"])
    if strategy == "corpus":
        return rng.choice(_HAND_CORPUS)
    elif strategy == "ascii":
        length = rng.randint(0, 800)
        return "".join(rng.choices(string.printable, k=length))
    elif strategy == "python_like":
        length = rng.randint(1, 50)
        return " ".join(rng.choices(_KEYWORDS, k=length))
    elif strategy == "unicode":
        return "".join(_safe_unicode_char(rng) for _ in range(rng.randint(5, 300)))
    elif strategy == "mixed":
        parts = [rand_script(rng) for _ in range(rng.randint(2, 4))]
        return "\n".join(parts)
    else:  # long
        line = rng.choice(["x = 1", "# comment", "import os", ""])
        return (line + "\n") * rng.randint(1000, 6000)


# ---------------------------------------------------------------------------
# Mock subprocess factory
# ---------------------------------------------------------------------------

def _make_fast_proc() -> MagicMock:
    proc = MagicMock()
    proc.pid = 1
    proc.stdin = MagicMock()
    proc.stdout.readline.side_effect = [
        b"##SEMPIPES_NODE_CODE##\n",
        (json.dumps({"index": 0, "code": "# mock"}) + "\n").encode(),
        b"##END##\n",
        b"",
    ]
    proc.wait.return_value = 0
    proc.returncode = 0
    return proc


# ---------------------------------------------------------------------------
# Invariant checkers
# ---------------------------------------------------------------------------

def check_compile(script: str) -> str | None:
    """Returns error string if invariant violated, else None."""
    try:
        resp = client.post("/api/compile", json={"input_code": script, "use_dynamic": False})
    except Exception as e:
        return f"EXCEPTION: {type(e).__name__}: {e}"
    if resp.status_code != 200:
        return f"Non-200: {resp.status_code}: {resp.text[:200]}"
    try:
        data = resp.json()
    except Exception as e:
        return f"Non-JSON response: {e}: {resp.text[:200]}"
    for field in ("nodes", "edges", "validation_errors"):
        if field not in data:
            return f"Missing field '{field}'"
        if not isinstance(data[field], list):
            return f"Field '{field}' is not a list"
    if "Traceback (most recent call last)" in resp.text:
        return "Traceback leaked into response body"
    return None


def check_execute(script: str) -> str | None:
    """Returns error string if invariant violated, else None."""
    proc = _make_fast_proc()
    try:
        with patch(POPEN_TARGET, lambda *a, **kw: proc), patch(SLEEP_TARGET, lambda _: None):
            resp = client.post("/api/execute", json={"input_code": script})
    except Exception as e:
        return f"EXCEPTION: {type(e).__name__}: {e}"
    if resp.status_code != 200:
        return f"Non-200: {resp.status_code}: {resp.text[:200]}"
    if "text/event-stream" not in resp.headers.get("content-type", ""):
        return f"Wrong content-type: {resp.headers.get('content-type')}"
    if "Traceback (most recent call last)" in resp.text:
        return "Traceback leaked into response body"
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    types = [e.get("type") for e in events]
    if "done" not in types and "error" not in types:
        return f"No 'done'/'error' event in stream. Got: {types}"
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(duration_seconds: int = 600) -> list[dict]:
    rng = random.Random()  # seeded from OS entropy — different every run
    deadline = time.time() + duration_seconds
    start = time.time()
    total = 0
    failures: list[dict] = []
    last_report = time.time()

    print(f"Fuzzing for {duration_seconds}s with a fresh random seed. Ctrl+C to stop early.")
    print("=" * 60)

    while time.time() < deadline:
        script = rand_script(rng)
        total += 1

        for endpoint, checker in [("compile", check_compile), ("execute", check_execute)]:
            err = checker(script)
            if err:
                failures.append({"endpoint": endpoint, "error": err, "script": script})
                print(f"\n  FAIL [{total}] /{endpoint}: {err}")
                print(f"        script: {repr(script[:120])}\n")

        if time.time() - last_report >= 60:
            elapsed = time.time() - start
            rate = total / elapsed
            remaining = deadline - time.time()
            print(
                f"  [{elapsed:.0f}s elapsed | {remaining:.0f}s left] "
                f"iterations={total} ({rate:.1f}/s)  failures={len(failures)}"
            )
            last_report = time.time()

    elapsed = time.time() - start
    print("=" * 60)
    print(f"Done. {total} iterations in {elapsed:.1f}s ({total/elapsed:.1f}/s). "
          f"{len(failures)} failure(s).")
    if failures:
        print("\nFAILURES:")
        for i, f in enumerate(failures, 1):
            print(f"  {i}. [{f['endpoint']}] {f['error']}")
            print(f"     script: {repr(f['script'][:150])}")
    return failures


if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    fails = run(duration)
    sys.exit(1 if fails else 0)
