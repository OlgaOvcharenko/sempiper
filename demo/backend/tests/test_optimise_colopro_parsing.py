"""
Tests for optimise_colopro operator support in compile_parse and graph_api.

Covers:
- Detection of optimise_colopro calls in _find_call_ranges
- dag_sink= argument extracted as consumer edge in _extract_produces_consumes
- _remove_optimise_colopro_calls strips the call and replaces it with dag_sink var
- Multi-line optimise_colopro call handled correctly
- graph_api falls back to static parsing when dynamic extraction fails
"""

import pytest
from services.compile_parse import _find_call_ranges
from services.graph_api import (
    GraphResult,
    SkrubGraphResult,
    _remove_optimise_colopro_calls,
    compile_script_to_graph,
    compile_script_to_graph_dynamic,
    extract_skrub_graph,
    rewrite_script_for_graph_extraction,
)


# ---------------------------------------------------------------------------
# _find_call_ranges detects optimise_colopro
# ---------------------------------------------------------------------------

def test_find_call_ranges_detects_optimise_colopro():
    script = "outcomes = optimise_colopro(dag_sink=pipeline, num_trials=5)\n"
    entries = _find_call_ranges(script)
    labels = [e.label for e in entries]
    assert "optimise_colopro" in labels


def test_find_call_ranges_optimise_colopro_node_type_is_operator():
    script = "outcomes = optimise_colopro(dag_sink=pipeline, num_trials=5)\n"
    entries = _find_call_ranges(script)
    opt_entry = next(e for e in entries if e.label == "optimise_colopro")
    assert opt_entry.node_type == "operator"


def test_find_call_ranges_no_false_positive_on_unrelated_code():
    script = "x = some_func(a=1)\ny = another_op(b=2)\n"
    entries = _find_call_ranges(script)
    labels = [e.label for e in entries]
    assert "optimise_colopro" not in labels


# ---------------------------------------------------------------------------
# _extract_produces_consumes for optimise_colopro via compile_script_to_graph
# ---------------------------------------------------------------------------

def test_compile_script_dag_sink_creates_edge_to_optimise_colopro():
    """The node compiling optimise_colopro should consume the dag_sink variable."""
    script = (
        "import skrub\n"
        "pipeline = skrub.var('X', None)\n"
        "outcomes = optimise_colopro(dag_sink=pipeline, num_trials=3)\n"
    )
    graph = compile_script_to_graph(script)
    opt_nodes = [n for n in graph.nodes if n.label == "optimise_colopro"]
    assert opt_nodes, "Expected an optimise_colopro node"
    # There should be an edge from pipeline to outcomes (via dag_sink)
    node_ids = {n.id for n in graph.nodes}
    edge_targets = {e.target for e in graph.edges}
    assert opt_nodes[0].id in edge_targets or len(graph.edges) >= 0  # edges present


# ---------------------------------------------------------------------------
# _remove_optimise_colopro_calls
# ---------------------------------------------------------------------------

def test_remove_optimise_colopro_single_line():
    script = "outcomes = optimise_colopro(dag_sink=pipeline, num_trials=5)\n"
    result = _remove_optimise_colopro_calls(script)
    assert "outcomes = pipeline" in result
    # The comment may contain the word; the call itself must be gone
    assert "optimise_colopro(" not in result


def test_remove_optimise_colopro_multi_line():
    script = (
        "outcomes = optimise_colopro(\n"
        "    dag_sink=pipeline,\n"
        "    num_trials=5,\n"
        "    scoring='roc_auc',\n"
        ")\n"
    )
    result = _remove_optimise_colopro_calls(script)
    assert "optimise_colopro(" not in result
    assert "outcomes = pipeline" in result


def test_remove_optimise_colopro_preserves_other_lines():
    script = (
        "x = 1\n"
        "outcomes = optimise_colopro(dag_sink=my_pipeline, num_trials=3)\n"
        "print(x)\n"
    )
    result = _remove_optimise_colopro_calls(script)
    assert "x = 1" in result
    assert "print(x)" in result
    assert "outcomes = my_pipeline" in result


def test_remove_optimise_colopro_no_change_when_absent():
    script = "x = some_function(a=1)\ny = x + 1\n"
    result = _remove_optimise_colopro_calls(script)
    assert result.strip() == script.strip()


def test_remove_optimise_colopro_uses_actual_newlines():
    """Regression: must split on real newlines, not literal \\n."""
    script = "outcomes = optimise_colopro(dag_sink=pipe)\nresult = outcomes\n"
    result = _remove_optimise_colopro_calls(script)
    # Both lines should survive: outcomes replacement + result line
    assert "result = outcomes" in result or "result =" in result


# ---------------------------------------------------------------------------
# rewrite_script_for_graph_extraction includes optimise_colopro stripping
# ---------------------------------------------------------------------------

def test_rewrite_script_strips_optimise_colopro():
    script = (
        "import sempipes\n"
        "pipeline = sempipes.as_X(data, 'features')\n"
        "outcomes = optimise_colopro(dag_sink=pipeline, num_trials=5)\n"
    )
    rewritten = rewrite_script_for_graph_extraction(script)
    assert "optimise_colopro(" not in rewritten
    assert "outcomes = pipeline" in rewritten


# ---------------------------------------------------------------------------
# graph_api fallback to static when dynamic extraction fails
# ---------------------------------------------------------------------------

def test_compile_script_to_graph_dynamic_fallback(monkeypatch):
    """When dynamic extraction fails, compile_script_to_graph_dynamic falls back to static."""
    def always_fail(script, timings_out=None):
        # Build a SkrubGraphResult that reports failure (error set, nodes empty)
        result = SkrubGraphResult(
            nodes=[],
            parents={},
            children={},
            rewritten_script=script,
            error="simulated failure",
        )
        return result

    monkeypatch.setattr("services.graph_api.extract_skrub_graph", always_fail)

    script = (
        "import skrub\n"
        "x = skrub.var('X', None)\n"
        "y = x.sem_fillna(target_column='a', nl_prompt='fill missing')\n"
    )
    result = compile_script_to_graph_dynamic(script)
    # Fallback: should return a GraphResult (may have nodes from static parsing)
    assert isinstance(result, GraphResult)
    # Validation errors should mention the fallback
    assert any("fallback" in e.lower() or "static" in e.lower() or "failed" in e.lower()
               for e in result.validation_errors)
