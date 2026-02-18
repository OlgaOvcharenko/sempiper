"""
Tests for node code assignment logic in execute_stream.py.

Verifies that:
1. Semantic operators (sem_*, apply, etc.) receive generated code
2. Non-semantic operators (subsample, eval, etc.) receive mock code
3. Code is correctly assigned to the right nodes (no misalignment)
"""

import json
import pytest
from unittest.mock import MagicMock
from services.execute_stream import stream_execute_events, _is_semantic_operator


def test_is_semantic_operator_classification():
    """Test that _is_semantic_operator correctly classifies operators."""
    # Semantic operators (should generate code)
    assert _is_semantic_operator("sem_fillna") is True
    assert _is_semantic_operator("sem_gen_features") is True
    assert _is_semantic_operator("sem_extract_features") is True
    assert _is_semantic_operator("sem_clean") is True
    assert _is_semantic_operator("sem_augment") is True
    assert _is_semantic_operator("sem_agg_features") is True
    assert _is_semantic_operator("sem_refine") is True
    assert _is_semantic_operator("sem_select") is True
    assert _is_semantic_operator("sem_distill") is True
    assert _is_semantic_operator("apply_with_sem_choose") is True
    assert _is_semantic_operator("sem_choose") is True
    assert _is_semantic_operator("apply") is True
    assert _is_semantic_operator("Apply some operator") is True  # Raw skrub Apply nodes

    # Non-semantic operators (should NOT generate code)
    assert _is_semantic_operator("skb.subsample") is False
    assert _is_semantic_operator("skb.eval") is False
    assert _is_semantic_operator("skb.apply") is False
    assert _is_semantic_operator("subsample") is False
    assert _is_semantic_operator("groupby") is False
    assert _is_semantic_operator("merge") is False
    assert _is_semantic_operator("drop") is False

    # Edge cases
    assert _is_semantic_operator("") is False
    assert _is_semantic_operator(None) is False


def _mock_subprocess_with_captured_codes(codes: list[str]) -> list[bytes]:
    """
    Create mock subprocess stdout with ##SEMPIPES_NODE_CODE## blocks.
    codes: list of code strings (one per semantic operator)
    """
    lines = []
    for i, code in enumerate(codes):
        lines.append(b"##SEMPIPES_NODE_CODE##\n")
        lines.append((json.dumps({
            "index": i,
            "code": code,
            "cost_usd": 0.01 * (i + 1),
            "attempts": 1
        }) + "\n").encode("utf-8"))
        lines.append(b"##END##\n")
    lines.append(b"")  # readline returns b"" and reader thread stops
    return lines


def test_subsample_does_not_get_generated_code(monkeypatch):
    """Subsample (non-semantic) should not receive generated code from semantic operators."""
    script = """
import skrub
import sempipes

products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=3)
result = products.skb.eval()
"""

    # Mock subprocess to return one code block (for sem_gen_features only)
    sem_gen_code = "def generate_features(df):\n    # Generated code\n    return df"

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = _mock_subprocess_with_captured_codes([sem_gen_code])
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)

    # Collect events from stream
    events_bytes = list(stream_execute_events(script, cache_key=None, temperature=0.7, llm_name="gpt-4o"))
    events = []
    for chunk in events_bytes:
        decoded = chunk.decode("utf-8")
        if decoded.startswith("data: "):
            events.append(json.loads(decoded[6:]))

    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # Find events for subsample and sem_gen_features
    subsample_events = [e for e in node_code_events if "subsample" in e.get("node_id", "").lower()]
    sem_gen_events = [e for e in node_code_events if "sem_gen_features" in e.get("node_id", "").lower()]

    assert len(subsample_events) > 0, "Should have subsample event"
    assert len(sem_gen_events) > 0, "Should have sem_gen_features event"

    subsample_event = subsample_events[0]
    sem_gen_event = sem_gen_events[0]

    # Verify subsample gets mock code (is_fallback=True)
    assert subsample_event["is_fallback"] is True, "Subsample should get mock code (is_fallback=True)"
    assert "Placeholder" in subsample_event["generated_code"] or "mock" in subsample_event["generated_code"].lower()

    # Verify sem_gen_features gets real code (is_fallback=False)
    assert sem_gen_event["is_fallback"] is False, "sem_gen_features should get real code (is_fallback=False)"
    assert sem_gen_code in sem_gen_event["generated_code"]

    # Verify they have different code
    assert subsample_event["generated_code"] != sem_gen_event["generated_code"]


def test_sem_gen_features_gets_correct_code(monkeypatch):
    """Verify sem_gen_features receives its own generated code, not code from other operators."""
    script = """
import skrub
import sempipes

df = skrub.var("df", dataset.employee)
df = df.sem_gen_features(nl_prompt="Generate employee features.", name="features", how_many=2)
result = df.skb.eval()
"""

    # Mock subprocess to return one code block for sem_gen_features
    sem_gen_code = "def generate_employee_features(df):\n    # Employee features\n    return df"

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = _mock_subprocess_with_captured_codes([sem_gen_code])
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)

    # Collect events
    events_bytes = list(stream_execute_events(script, cache_key=None, temperature=0.7, llm_name="gpt-4o"))
    events = []
    for chunk in events_bytes:
        decoded = chunk.decode("utf-8")
        if decoded.startswith("data: "):
            events.append(json.loads(decoded[6:]))

    node_code_events = [e for e in events if e.get("type") == "node_code"]
    sem_gen_events = [e for e in node_code_events if "sem_gen_features" in e.get("node_id", "").lower()]

    assert len(sem_gen_events) > 0
    sem_gen_event = sem_gen_events[0]

    assert sem_gen_event["is_fallback"] is False
    assert sem_gen_code in sem_gen_event["generated_code"]
    assert sem_gen_event["cost_usd"] > 0  # Should have cost from mock


def test_mixed_semantic_nonsemantic_operators(monkeypatch):
    """Pipeline with both semantic and non-semantic operators should assign code correctly."""
    script = """
import skrub
import sempipes

df = skrub.var("df", dataset.employee)
df = df.sem_fillna(nl_prompt="Fill missing values", name="filled")
df = df.skb.subsample(n=50)
df = df.sem_gen_features(nl_prompt="Generate features", name="features", how_many=2)
result = df.skb.eval()
"""

    # Mock subprocess to return two code blocks (for sem_fillna and sem_gen_features)
    sem_fillna_code = "def fill_missing(df):\n    # Fill code\n    return df"
    sem_gen_code = "def generate_features(df):\n    # Gen features code\n    return df"

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = _mock_subprocess_with_captured_codes([sem_fillna_code, sem_gen_code])
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)

    # Collect events
    events_bytes = list(stream_execute_events(script, cache_key=None, temperature=0.7, llm_name="gpt-4o"))
    events = []
    for chunk in events_bytes:
        decoded = chunk.decode("utf-8")
        if decoded.startswith("data: "):
            events.append(json.loads(decoded[6:]))

    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # Find events for each operator
    sem_fillna_events = [e for e in node_code_events if "sem_fillna" in e.get("node_id", "").lower()]
    subsample_events = [e for e in node_code_events if "subsample" in e.get("node_id", "").lower()]
    sem_gen_events = [e for e in node_code_events if "sem_gen_features" in e.get("node_id", "").lower()]

    assert len(sem_fillna_events) > 0, "Should have sem_fillna event"
    assert len(subsample_events) > 0, "Should have subsample event"
    assert len(sem_gen_events) > 0, "Should have sem_gen_features event"

    # Verify sem_fillna gets its own code
    fillna_event = sem_fillna_events[0]
    assert fillna_event["is_fallback"] is False
    assert sem_fillna_code in fillna_event["generated_code"]

    # Verify subsample gets mock code
    subsample_event = subsample_events[0]
    assert subsample_event["is_fallback"] is True
    assert "Placeholder" in subsample_event["generated_code"] or "mock" in subsample_event["generated_code"].lower()

    # Verify sem_gen_features gets its own code (not sem_fillna's)
    gen_event = sem_gen_events[0]
    assert gen_event["is_fallback"] is False
    assert sem_gen_code in gen_event["generated_code"]
    assert sem_fillna_code not in gen_event["generated_code"]

    # Verify all three have different code
    codes = [fillna_event["generated_code"], subsample_event["generated_code"], gen_event["generated_code"]]
    assert len(set(codes)) == 3, "All three operators should have different code"


def test_multiple_semantic_operators_in_sequence(monkeypatch):
    """Multiple semantic operators in sequence should each get their own code."""
    script = """
import skrub
import sempipes

df = skrub.var("df", dataset.employee)
df = df.sem_fillna(nl_prompt="Fill missing", name="filled")
df = df.sem_clean(nl_prompt="Clean data", name="cleaned")
df = df.sem_gen_features(nl_prompt="Generate features", name="features", how_many=2)
result = df.skb.eval()
"""

    # Mock subprocess to return three code blocks
    codes = [
        "def fill_missing(df):\n    # Fill code\n    return df",
        "def clean_data(df):\n    # Clean code\n    return df",
        "def generate_features(df):\n    # Gen code\n    return df"
    ]

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = _mock_subprocess_with_captured_codes(codes)
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)

    # Collect events
    events_bytes = list(stream_execute_events(script, cache_key=None, temperature=0.7, llm_name="gpt-4o"))
    events = []
    for chunk in events_bytes:
        decoded = chunk.decode("utf-8")
        if decoded.startswith("data: "):
            events.append(json.loads(decoded[6:]))

    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # Find events for each operator
    fillna_events = [e for e in node_code_events if "sem_fillna" in e.get("node_id", "").lower()]
    clean_events = [e for e in node_code_events if "sem_clean" in e.get("node_id", "").lower()]
    gen_events = [e for e in node_code_events if "sem_gen_features" in e.get("node_id", "").lower()]

    assert len(fillna_events) > 0
    assert len(clean_events) > 0
    assert len(gen_events) > 0

    # Verify each gets its own code
    assert codes[0] in fillna_events[0]["generated_code"]
    assert codes[1] in clean_events[0]["generated_code"]
    assert codes[2] in gen_events[0]["generated_code"]

    # Verify all are not fallbacks
    assert fillna_events[0]["is_fallback"] is False
    assert clean_events[0]["is_fallback"] is False
    assert gen_events[0]["is_fallback"] is False
