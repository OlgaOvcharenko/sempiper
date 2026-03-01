"""Single-sink graph tests for pipeline scripts and optimizer scripts.

Verifies that after _prune_dead_branches the compiled graph has exactly ONE
sink node (a node with no outgoing edges).  Dead-end branches and isolated
nodes must be removed, leaving only the intended pipeline output as the sink.

Covers:
  - pipeline_scripts/fraud.py  (groupby + skb.apply_func were dead ends)
  - optimizer_scripts/optimise_fraud.py  (drop isolated from chained .merge().drop())
  - optimizer_scripts/optimise_house.py
  - optimizer_scripts/optimise_museums.py
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.compile_parse import extract_nodes_with_ranges

# Re-use verbatim fraud script from the source-range test module.
from test_new_scripts_source_ranges import FRAUD_SCRIPT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def _load_optimizer_script(filename: str) -> str:
    path = os.path.join(_REPO_ROOT, "optimizer_scripts", filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _sink_nodes(nodes, edges):
    """Return nodes that have no outgoing edges (sink = leaf in the DAG)."""
    sources = {e.source for e in edges}
    return [n for n in nodes if n.id not in sources]


def _assert_exactly_one_sink(script: str, script_name: str) -> None:
    nodes, edges = extract_nodes_with_ranges(script)
    assert nodes, f"{script_name}: parser returned no nodes"

    sinks = _sink_nodes(nodes, edges)
    assert len(sinks) == 1, (
        f"{script_name}: expected exactly 1 sink node, got {len(sinks)}:\n"
        + "\n".join(f"  - {n.label!r} (id={n.id!r})" for n in sinks)
    )


def _assert_no_isolated_nodes(script: str, script_name: str) -> None:
    nodes, edges = extract_nodes_with_ranges(script)
    assert nodes, f"{script_name}: parser returned no nodes"

    nodes_in_edges: set[str] = {e.source for e in edges} | {e.target for e in edges}
    isolated = [n for n in nodes if n.id not in nodes_in_edges]
    assert isolated == [], (
        f"{script_name}: {len(isolated)} isolated node(s) with no edges:\n"
        + "\n".join(f"  - {n.label!r} (id={n.id!r})" for n in isolated)
    )


# ---------------------------------------------------------------------------
# fraud.py (pipeline_scripts)
# ---------------------------------------------------------------------------


class TestFraudSingleSink:
    """fraud.py: groupby and skb.apply_func are dead ends and must be pruned."""

    def setup_method(self):
        self.nodes, self.edges = extract_nodes_with_ranges(FRAUD_SCRIPT)

    def test_exactly_one_sink(self):
        """After pruning the only sink is the final skb.apply (catboost)."""
        _assert_exactly_one_sink(FRAUD_SCRIPT, "fraud.py")

    def test_no_isolated_nodes(self):
        _assert_no_isolated_nodes(FRAUD_SCRIPT, "fraud.py")

    def test_sink_is_skb_apply(self):
        """The single sink must be a skb.apply node (the CatBoost classifier)."""
        sinks = _sink_nodes(self.nodes, self.edges)
        assert len(sinks) == 1
        assert sinks[0].label == "skb.apply", (
            f"Expected sink label 'skb.apply', got {sinks[0].label!r}"
        )

    def test_groupby_node_pruned(self):
        """groupby produces a dead-end analysis variable → must be pruned."""
        groupby_nodes = [n for n in self.nodes if "groupby" in n.label.lower()]
        assert groupby_nodes == [], (
            f"groupby dead-end node must be pruned, but found: "
            + ", ".join(n.label for n in groupby_nodes)
        )

    def test_apply_func_node_pruned(self):
        """skb.apply_func with no LHS (side-effect only) → must be pruned."""
        apply_func_nodes = [n for n in self.nodes if n.label == "skb.apply_func"]
        assert apply_func_nodes == [], (
            f"skb.apply_func dead-end node must be pruned, but found "
            f"{len(apply_func_nodes)} node(s)"
        )


# ---------------------------------------------------------------------------
# optimise_fraud.py
# ---------------------------------------------------------------------------


class TestOptimiseFraudGraph:
    """optimise_fraud.py: isolated drop node from chained .merge().drop() must be pruned."""

    def setup_method(self):
        self.script = _load_optimizer_script("optimise_fraud.py")
        self.nodes, self.edges = extract_nodes_with_ranges(self.script)

    def test_parser_returns_nodes(self):
        assert self.nodes, "optimise_fraud.py: parser returned no nodes"

    def test_no_isolated_nodes(self):
        _assert_no_isolated_nodes(self.script, "optimise_fraud.py")

    def test_exactly_one_sink(self):
        _assert_exactly_one_sink(self.script, "optimise_fraud.py")

    def test_sink_is_skb_apply(self):
        """The single sink must be a skb.apply node (the CatBoost classifier)."""
        sinks = _sink_nodes(self.nodes, self.edges)
        assert len(sinks) == 1
        assert sinks[0].label == "skb.apply", (
            f"Expected sink label 'skb.apply', got {sinks[0].label!r}"
        )


# ---------------------------------------------------------------------------
# optimise_house.py
# ---------------------------------------------------------------------------


class TestOptimiseHouseGraph:
    """optimise_house.py: compiled graph must have exactly one sink."""

    def setup_method(self):
        self.script = _load_optimizer_script("optimise_house.py")
        self.nodes, self.edges = extract_nodes_with_ranges(self.script)

    def test_parser_returns_nodes(self):
        assert self.nodes, "optimise_house.py: parser returned no nodes"

    def test_no_isolated_nodes(self):
        _assert_no_isolated_nodes(self.script, "optimise_house.py")

    def test_exactly_one_sink(self):
        _assert_exactly_one_sink(self.script, "optimise_house.py")

    def test_sink_is_skb_apply(self):
        """The single sink must be a skb.apply node (the TabPFN regressor)."""
        sinks = _sink_nodes(self.nodes, self.edges)
        assert len(sinks) == 1
        assert sinks[0].label == "skb.apply", (
            f"Expected sink label 'skb.apply', got {sinks[0].label!r}"
        )


# ---------------------------------------------------------------------------
# optimise_museums.py
# ---------------------------------------------------------------------------


class TestOptimiseMuseumsGraph:
    """optimise_museums.py: compiled graph must have exactly one sink."""

    def setup_method(self):
        self.script = _load_optimizer_script("optimise_museums.py")
        self.nodes, self.edges = extract_nodes_with_ranges(self.script)

    def test_parser_returns_nodes(self):
        assert self.nodes, "optimise_museums.py: parser returned no nodes"

    def test_no_isolated_nodes(self):
        _assert_no_isolated_nodes(self.script, "optimise_museums.py")

    def test_exactly_one_sink(self):
        _assert_exactly_one_sink(self.script, "optimise_museums.py")

    def test_sink_is_skb_apply(self):
        """The single sink must be a skb.apply node (the FTTransformer classifier)."""
        sinks = _sink_nodes(self.nodes, self.edges)
        assert len(sinks) == 1
        assert sinks[0].label == "skb.apply", (
            f"Expected sink label 'skb.apply', got {sinks[0].label!r}"
        )
