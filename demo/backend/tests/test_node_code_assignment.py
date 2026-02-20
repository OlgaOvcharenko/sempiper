"""
Tests for node code assignment logic in execute_stream.py.

Verifies that:
1. Semantic operators (sem_*, apply_with_sem_choose) receive generated code (node_code events)
2. Non-semantic operators (subsample, eval, etc.) receive data summaries (input_summary events)
3. Code is correctly assigned to the right semantic operators (no misalignment)
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

    # Non-semantic operators (should NOT generate code - should get data summaries)
    assert _is_semantic_operator("skb.subsample") is False
    assert _is_semantic_operator("skb.eval") is False
    assert _is_semantic_operator("skb.apply") is False
    assert _is_semantic_operator("subsample") is False
    assert _is_semantic_operator("SubsamplePreviews") is False
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


def test_multiple_semantic_operators_in_sequence(monkeypatch):
    """Multiple semantic operators in sequence should each get their own code."""
    script = """
import skrub
import sempipes

df = skrub.var("df", dataset.employee)
df = df.sem_fillna(nl_prompt="Fill missing", target_column="name", impute_with_existing_values_only=True)
df = df.sem_clean(nl_prompt="Clean data", target_column="address")
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
    fillna_events = [e for e in node_code_events if "sem_fillna" in str(e.get("node_id", "")).lower()]
    clean_events = [e for e in node_code_events if "sem_clean" in str(e.get("node_id", "")).lower()]
    gen_events = [e for e in node_code_events if "sem_gen_features" in str(e.get("node_id", "")).lower()]

    assert len(fillna_events) > 0, "Should have sem_fillna event"
    assert len(clean_events) > 0, "Should have sem_clean event"
    assert len(gen_events) > 0, "Should have sem_gen_features event"

    # Verify each gets its own code
    assert codes[0] in fillna_events[0]["generated_code"], "sem_fillna should have its code"
    assert codes[1] in clean_events[0]["generated_code"], "sem_clean should have its code"
    assert codes[2] in gen_events[0]["generated_code"], "sem_gen_features should have its code"

    # Verify all are not fallbacks
    assert fillna_events[0]["is_fallback"] is False
    assert clean_events[0]["is_fallback"] is False
    assert gen_events[0]["is_fallback"] is False
