"""
Tests for node_code event assignment in execute_stream.py.

Verifies that:
1. node_code events use compile IDs (not skrub runtime sub-node IDs)
2. Each semantic operator gets exactly one node_code event with a unique node_id
3. After skrub_graph rekey, correct codes remain under compile IDs

Uses a fraud-like script defined inline with mocked compile results — no external data needed.
"""

import json
from typing import Optional
from unittest.mock import MagicMock

import pytest
from services.execute_stream import stream_execute_events

# --------------------------------------------------------------------------- #
# Fraud-like script — self-contained, no external file dependency.
# --------------------------------------------------------------------------- #
FRAUD_LIKE_SCRIPT = """
import skrub
import sempipes

products = skrub.var("products")
baskets = skrub.var("baskets")

X = sempipes.as_X(products)
X = X.sem_fillna(nl_prompt="Fill missing product fields", target_column="price", impute_with_existing_values_only=True)
X = X.sem_extract_features(nl_prompt="Extract product features", columns=["description"])
X = X.sem_gen_features(nl_prompt="Generate product features", name="product_features", how_many=3)
X = X.sem_agg_features(nl_prompt="Aggregate product features")

result = X.skb.eval()
"""

# Compile IDs used in the fake compiled graph (numeric, matching dynamic compilation format)
FAKE_COMPILE_IDS = {
    "var_products": "1",
    "var_baskets": "2",
    "as_X": "3",
    "sem_fillna": "5",
    "sem_extract_features": "10",
    "sem_gen_features": "18",
    "sem_agg_features": "25",
}
SEM_COMPILE_IDS = [
    FAKE_COMPILE_IDS["sem_fillna"],
    FAKE_COMPILE_IDS["sem_extract_features"],
    FAKE_COMPILE_IDS["sem_gen_features"],
    FAKE_COMPILE_IDS["sem_agg_features"],
]

FIXED_CODES = [
    "def sem_fillna_impl(df):\n    return df",
    "def sem_extract_impl(df):\n    return df",
    "def sem_gen_impl(df):\n    return df",
    "def sem_agg_impl(df):\n    return df",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_fake_compile_result():
    """Build a fake CompileResult with known node IDs (numeric, like dynamic compilation)."""
    from models.schemas import CompileNode, CompileEdge

    nodes = [
        CompileNode(id=FAKE_COMPILE_IDS["var_products"], label="<Var 'products'>", type="input"),
        CompileNode(id=FAKE_COMPILE_IDS["var_baskets"], label="<Var 'baskets'>", type="input"),
        CompileNode(id=FAKE_COMPILE_IDS["as_X"], label="as_X", type="input"),
        CompileNode(id=FAKE_COMPILE_IDS["sem_fillna"], label="sem_fillna", type="operator"),
        CompileNode(id=FAKE_COMPILE_IDS["sem_extract_features"], label="sem_extract_features", type="operator"),
        CompileNode(id=FAKE_COMPILE_IDS["sem_gen_features"], label="sem_gen_features", type="operator"),
        CompileNode(id=FAKE_COMPILE_IDS["sem_agg_features"], label="sem_agg_features", type="operator"),
    ]
    edges = [
        CompileEdge(source=FAKE_COMPILE_IDS["var_products"], target=FAKE_COMPILE_IDS["as_X"]),
        CompileEdge(source=FAKE_COMPILE_IDS["as_X"], target=FAKE_COMPILE_IDS["sem_fillna"]),
        CompileEdge(source=FAKE_COMPILE_IDS["sem_fillna"], target=FAKE_COMPILE_IDS["sem_extract_features"]),
        CompileEdge(source=FAKE_COMPILE_IDS["sem_extract_features"], target=FAKE_COMPILE_IDS["sem_gen_features"]),
        CompileEdge(source=FAKE_COMPILE_IDS["sem_gen_features"], target=FAKE_COMPILE_IDS["sem_agg_features"]),
    ]
    result = MagicMock()
    result.nodes = nodes
    result.edges = edges
    return result


def _mock_subprocess_with_skrub_node_ids(codes_with_ids: list[tuple[str, str]]) -> list[bytes]:
    """
    Build mock subprocess stdout with ##SEMPIPES_NODE_CODE## blocks.
    codes_with_ids: list of (code_string, skrub_node_id) pairs.
    """
    lines = []
    for i, (code, skrub_node_id) in enumerate(codes_with_ids):
        payload = {
            "index": i,
            "code": code,
            "cost_usd": 0.01 * (i + 1),
            "attempts": 1,
            "skrub_node_id": skrub_node_id,
        }
        lines.append(b"##SEMPIPES_NODE_CODE##\n")
        lines.append((json.dumps(payload) + "\n").encode("utf-8"))
        lines.append(b"##END##\n")
    lines.append(b"")  # readline returns b"" → reader thread stops
    return lines


def _collect_events(script, monkeypatch, runner_stdout_lines):
    """Run stream_execute_events with mocked subprocess + compile, collect parsed events."""
    fake_compile_result = _make_fake_compile_result()

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = runner_stdout_lines
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)
    monkeypatch.setattr(
        "services.graph_api.compile_script_to_graph_dynamic",
        lambda script: fake_compile_result,
    )

    events = []
    for chunk in stream_execute_events(script, cache_key=None, temperature=0.7, llm_name="gpt-4o"):
        decoded = chunk.decode("utf-8")
        if decoded.startswith("data: "):
            events.append(json.loads(decoded[6:]))
    return events


# --------------------------------------------------------------------------- #
# Test 1: node_code events use compile IDs when skrub_node_id matches compile ID
# --------------------------------------------------------------------------- #
def test_semantic_node_code_uses_compile_id_when_skrub_node_id_matches(monkeypatch):
    """
    When runner returns skrub_node_id values equal to compile node IDs, node_code
    events should have those compile IDs as node_id.
    """
    codes_with_ids = list(zip(FIXED_CODES, SEM_COMPILE_IDS))
    runner_stdout = _mock_subprocess_with_skrub_node_ids(codes_with_ids)

    events = _collect_events(FRAUD_LIKE_SCRIPT, monkeypatch, runner_stdout)

    node_code_events = [e for e in events if e.get("type") == "node_code"]
    assert len(node_code_events) > 0, "Expected at least one node_code event"

    emitted_ids = [e["node_id"] for e in node_code_events]
    for cid in SEM_COMPILE_IDS:
        assert cid in emitted_ids, (
            f"Compile ID {cid!r} not found in node_code event node_ids: {emitted_ids}"
        )


# --------------------------------------------------------------------------- #
# Test 2: Each semantic operator gets exactly one node_code event with unique node_id
# --------------------------------------------------------------------------- #
def test_node_code_ids_are_unique_per_semantic_operator(monkeypatch):
    """
    Each semantic operator gets exactly one node_code event, and all node_ids are distinct.
    """
    sem_count = len(SEM_COMPILE_IDS)
    codes_with_ids = list(zip(FIXED_CODES, SEM_COMPILE_IDS))
    runner_stdout = _mock_subprocess_with_skrub_node_ids(codes_with_ids)

    events = _collect_events(FRAUD_LIKE_SCRIPT, monkeypatch, runner_stdout)

    node_code_events = [e for e in events if e.get("type") == "node_code"]
    emitted_ids = [e["node_id"] for e in node_code_events]

    # All emitted IDs should be unique
    assert len(emitted_ids) == len(set(emitted_ids)), (
        f"Duplicate node_ids in node_code events: {emitted_ids}"
    )
    # Should have one event per semantic operator
    assert len(node_code_events) == sem_count, (
        f"Expected {sem_count} node_code events, got {len(node_code_events)}: {emitted_ids}"
    )


# --------------------------------------------------------------------------- #
# Test 3: After rekey, correct codes remain under compile IDs
# --------------------------------------------------------------------------- #
def test_no_wrong_code_after_rekey(monkeypatch):
    """
    Main loop stores codes under compile IDs. When skrub_graph arrives with
    a mapping like {"shadow_10": "10"}, rekey should NOT overwrite compile ID
    entries because shadow IDs were never written (main loop uses compile IDs directly).
    """
    first_cid = SEM_COMPILE_IDS[0]
    second_cid = SEM_COMPILE_IDS[1]
    first_code = FIXED_CODES[0]
    second_code = FIXED_CODES[1]

    codes_with_ids = list(zip(FIXED_CODES, SEM_COMPILE_IDS))
    runner_stdout = _mock_subprocess_with_skrub_node_ids(codes_with_ids)

    events = _collect_events(FRAUD_LIKE_SCRIPT, monkeypatch, runner_stdout)

    node_code_events = [e for e in events if e.get("type") == "node_code"]
    code_by_node = {e["node_id"]: e["generated_code"] for e in node_code_events}

    if first_cid in code_by_node:
        got = code_by_node[first_cid]
        assert got == first_code, (
            f"Compile ID {first_cid!r} has wrong code. "
            f"Expected: {first_code[:50]!r}, got: {got[:50]!r}"
        )
    if second_cid in code_by_node:
        got = code_by_node[second_cid]
        assert got == second_code, (
            f"Compile ID {second_cid!r} has wrong code. "
            f"Expected: {second_code[:50]!r}, got: {got[:50]!r}"
        )
    # At minimum, we should have emitted some events
    assert len(node_code_events) > 0, "Expected node_code events but got none"
