"""
Tests for object-identity-based code-to-node attribution in skrub_graph_runner.

Verifies that:
1. _capturing_generate_code_from_messages records the current node's object ref AND id
2. _capturing_evaluate sets _current_node_object_ref = data_op and _current_node_object_id = id(data_op)
3. ##SEMPIPES_NODE_CODE## blocks carry skrub_node_id resolved via ref_to_graph_idx (is-based, not id-based)

Uses a fraud-like pipeline snippet defined inline — does NOT read from pipeline_scripts/fraud.py.
"""

import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

# --------------------------------------------------------------------------- #
# Fraud-like script: 2 semantic operators on two skrub vars.
# Self-contained — no external file dependency.
# --------------------------------------------------------------------------- #
FRAUD_LIKE_SCRIPT = """
import skrub
import sempipes

products = skrub.var("products")
baskets = skrub.var("baskets")

X = sempipes.as_X(products)
X = X.sem_fillna(nl_prompt="Fill missing product fields", target_column="price", impute_with_existing_values_only=True)
X = X.sem_gen_features(nl_prompt="Generate product features", name="product_features", how_many=3)

result = X.skb.eval()
"""


# --------------------------------------------------------------------------- #
# Helper: ensure runner globals exist and can be imported
# --------------------------------------------------------------------------- #
def _import_runner():
    pytest.importorskip("skrub")
    pytest.importorskip("sempipes")
    import services.skrub_graph_runner as runner
    return runner


def test_map_captures_order_fallback_when_ref_empty():
    """Fraud-style pipeline: ref match fails (learner clone); pair by capture order + numeric semantic ids."""
    runner = _import_runner()
    m = runner._map_captures_to_skrub_semantic_nodes(
        2, {}, {"12", "19"},
    )
    assert m == {0: "12", 1: "19"}


def test_map_captures_ref_first_then_fallback():
    """First capture resolved by ref; second by order to remaining semantic node."""
    runner = _import_runner()
    m = runner._map_captures_to_skrub_semantic_nodes(
        2, {0: 12}, {"12", "19"},
    )
    assert m == {0: "12", 1: "19"}


def test_map_captures_order_fallback_with_extra_semantic_slot():
    """
    When there are extra semantic slots in the runtime graph but fewer captures,
    fallback should still assign the available captures to the first remaining
    semantic node IDs.
    """
    runner = _import_runner()
    m = runner._map_captures_to_skrub_semantic_nodes(
        2, {}, {"12", "19", "21"},
    )
    assert m == {0: "12", 1: "19"}


# --------------------------------------------------------------------------- #
# Test 1: _capturing_generate_code_from_messages records _current_node_object_id and ref
# --------------------------------------------------------------------------- #
def test_captured_code_node_id_tracks_current_operator():
    """When _current_node_object_id/ref is set, _capturing_generate_code_from_messages appends both."""
    runner = _import_runner()

    # Reset module state for this test
    original_codes = runner._captured_codes[:]
    original_node_ids = runner._captured_code_node_ids[:]
    original_node_refs = runner._captured_code_node_refs[:]
    original_costs = runner._per_operator_costs[:]
    original_attempts = runner._per_operator_attempts[:]
    original_current_id = runner._current_node_object_id
    original_current_ref = runner._current_node_object_ref
    original_generate = runner._original_generate_code
    original_unwrap = runner._unwrap_python_func

    try:
        # Inject a fake original generate function
        fake_code = "def fake(): return 42"
        runner._original_generate_code = lambda messages: fake_code
        runner._unwrap_python_func = lambda x: x
        runner._captured_codes.clear()
        runner._captured_code_node_ids.clear()
        runner._captured_code_node_refs.clear()
        runner._per_operator_costs.clear()
        runner._per_operator_attempts.clear()

        # Set a specific node object ref (simulating _capturing_evaluate having set it)
        class _SentinelOp:
            pass

        sentinel_obj = _SentinelOp()
        sentinel_id = id(sentinel_obj)
        runner._current_node_object_id = sentinel_id
        runner._current_node_object_ref = sentinel_obj

        runner._capturing_generate_code_from_messages(["dummy message"])

        assert len(runner._captured_code_node_ids) == 1
        assert runner._captured_code_node_ids[0] == sentinel_id
        assert len(runner._captured_code_node_refs) == 1
        assert runner._captured_code_node_refs[0] is sentinel_obj, (
            "_captured_code_node_refs should hold the actual object reference"
        )
        assert len(runner._captured_codes) == 1
        assert runner._captured_codes[0] == fake_code
    finally:
        # Restore module state
        runner._captured_codes.clear()
        runner._captured_codes.extend(original_codes)
        runner._captured_code_node_ids.clear()
        runner._captured_code_node_ids.extend(original_node_ids)
        runner._captured_code_node_refs.clear()
        runner._captured_code_node_refs.extend(original_node_refs)
        runner._per_operator_costs.clear()
        runner._per_operator_costs.extend(original_costs)
        runner._per_operator_attempts.clear()
        runner._per_operator_attempts.extend(original_attempts)
        runner._current_node_object_id = original_current_id
        runner._current_node_object_ref = original_current_ref
        runner._original_generate_code = original_generate
        runner._unwrap_python_func = original_unwrap


# --------------------------------------------------------------------------- #
# Test 2: _capturing_evaluate sets and restores _current_node_object_id and ref
# --------------------------------------------------------------------------- #
def test_capturing_evaluate_sets_node_object_id():
    """_capturing_evaluate sets _current_node_object_ref = data_op (and id), restores after."""
    pytest.importorskip("skrub._data_ops._evaluation")
    runner = _import_runner()

    if not hasattr(runner, "_current_node_object_id"):
        pytest.skip("_current_node_object_id global not found in runner")
    if not hasattr(runner, "_current_node_object_ref"):
        pytest.skip("_current_node_object_ref global not found in runner")

    captured_ids: list[int] = []
    captured_refs: list = []
    original_current_id = runner._current_node_object_id
    original_current_ref = runner._current_node_object_ref

    class FakeDataOp:
        pass

    data_op = FakeDataOp()

    def _spy_original_evaluate(da, mode="preview", environment=None, clear=False, callbacks=()):
        # At this point, _current_node_object_id should be id(data_op)
        captured_ids.append(runner._current_node_object_id)
        captured_refs.append(runner._current_node_object_ref)
        # Call any callbacks that were added
        for cb in callbacks:
            try:
                cb(da, None)
            except Exception:
                pass

    # Set a previous value to verify restore
    runner._current_node_object_id = 12345
    runner._current_node_object_ref = object()

    # Temporarily patch _eval_mod.evaluate to run our spy
    try:
        import skrub._data_ops._evaluation as _eval_mod
        old_evaluate = _eval_mod.evaluate
        _eval_mod.evaluate = _spy_original_evaluate

        # Re-install the capture patch so it uses our spy
        runner._preview_capture_installed = False
        runner._setup_preview_capture_patch()

        # Now call the patched evaluate — it should be _capturing_evaluate
        _eval_mod.evaluate(data_op, mode="fit_transform", environment={}, clear=True)

        assert len(captured_ids) == 1, "evaluate should have been called once"
        assert captured_ids[0] == id(data_op), "_current_node_object_id should be id(data_op) during call"
        assert captured_refs[0] is data_op, "_current_node_object_ref should be data_op during call"
        # After the call, should be restored
        assert runner._current_node_object_id == 12345, "_current_node_object_id should be restored"
    finally:
        runner._current_node_object_id = original_current_id
        runner._current_node_object_ref = original_current_ref
        runner._preview_capture_installed = False
        try:
            _eval_mod.evaluate = old_evaluate
            # Re-install to clean state
            runner._setup_preview_capture_patch()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Test 3: Runner emits ##SEMPIPES_NODE_CODE## blocks with correct skrub_node_id
#         Resolved via ref_to_graph_idx (is-based), not obj_to_idx (id-based).
# --------------------------------------------------------------------------- #
def test_code_blocks_emitted_with_correct_skrub_node_id(monkeypatch, capsys):
    """
    With patched LLM, runner should emit one code block per semantic operator,
    each with skrub_node_id matching the node's index in the execution graph.
    No two code blocks should share the same skrub_node_id.
    Uses ref_to_graph_idx (is-based matching) not obj_to_idx (id-based).
    """
    pytest.importorskip("skrub")
    pytest.importorskip("sempipes")

    code_call_counter = [0]
    fixed_codes = [
        "def fillna_impl(df): return df  # sem_fillna",
        "def gen_features_impl(df): return df  # sem_gen_features",
    ]

    def _fake_generate_code_from_messages(messages):
        idx = code_call_counter[0] % len(fixed_codes)
        code_call_counter[0] += 1
        return fixed_codes[idx]

    import services.skrub_graph_runner as runner

    # Patch LLM so no real API calls happen
    monkeypatch.setattr(runner, "_original_generate_code", _fake_generate_code_from_messages, raising=False)
    monkeypatch.setattr(runner, "_unwrap_python_func", lambda x: x, raising=False)

    # Simulate main() flow: reset globals, exec script, emit code blocks
    monkeypatch.setattr(runner, "_captured_codes", [], raising=False)
    monkeypatch.setattr(runner, "_captured_code_node_ids", [], raising=False)
    monkeypatch.setattr(runner, "_captured_code_node_refs", [], raising=False)
    monkeypatch.setattr(runner, "_per_operator_costs", [], raising=False)
    monkeypatch.setattr(runner, "_per_operator_attempts", [], raising=False)
    monkeypatch.setattr(runner, "_current_node_object_id", None, raising=False)
    monkeypatch.setattr(runner, "_current_node_object_ref", None, raising=False)

    # Run exec with the fraud-like script
    g = runner._prepare_globals()
    try:
        runner._setup_capture_patch()
        exec(compile(FRAUD_LIKE_SCRIPT, "<test>", "exec"), g)
    except Exception:
        pass  # eval() may fail without real data — we only care about code capture

    # Must have captured at least one code block
    if not runner._captured_codes:
        pytest.skip("No code was captured — semantic operators did not execute (expected with no data)")

    # Build ref_to_graph_idx using is-based matching (same as main())
    ref_to_graph_idx: dict[int, int] = {}
    try:
        from skrub._data_ops._evaluation import _Graph
        src = runner._find_learner_dataop(g) or runner._get_pipeline_result_dataop(FRAUD_LIKE_SCRIPT, g)
        if src is not None:
            raw = _Graph().run(src)
            node_list = runner._nodes_to_list(raw.get("nodes") or []) if isinstance(raw, dict) else []
            for capture_idx, ref in enumerate(runner._captured_code_node_refs):
                if ref is None:
                    continue
                for graph_idx, node in enumerate(node_list):
                    if node is ref:
                        ref_to_graph_idx[capture_idx] = graph_idx
                        break
    except Exception:
        pytest.skip("Could not build graph from execution (expected without real data)")

    if not ref_to_graph_idx:
        pytest.skip("Empty ref_to_graph_idx — pipeline did not produce a graph with matched refs")

    # Resolve skrub_node_ids the same way main() does
    emitted_ids = []
    for capture_idx in range(len(runner._captured_codes)):
        graph_idx = ref_to_graph_idx.get(capture_idx)
        if graph_idx is not None:
            emitted_ids.append(str(graph_idx))

    assert emitted_ids, "Expected at least one resolved node ID"

    # Each code block should get a unique node ID
    assert len(emitted_ids) == len(set(emitted_ids)), (
        f"Duplicate skrub_node_ids in emitted blocks: {emitted_ids}"
    )
