"""Graph-connectivity tests for fraud.py, house_prices.py, and museums.py.

Verifies two properties of the compiled graph for each new pipeline script:

1. **No isolated nodes** — every node has at least one edge (appears as the
   source or target of at least one CompileEdge).

2. **Single connected component** — ignoring edge direction, all nodes belong
   to one connected component (there is no disconnected sub-graph).

If either assertion fails the script has a graph-connectivity bug where some
nodes appear in the visualization without being linked to the rest of the DAG.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.compile_parse import extract_nodes_with_ranges

# Re-use the verbatim script constants already embedded in the source-range
# test module so we test the exact same text without duplication.
from test_new_scripts_source_ranges import (
    FRAUD_SCRIPT,
    HOUSE_PRICES_SCRIPT,
    MUSEUMS_SCRIPT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connected_components(node_ids: list[str], edges) -> list[set[str]]:
    """Return list of connected components treating edges as undirected."""
    adjacency: dict[str, set[str]] = {nid: set() for nid in node_ids}
    for edge in edges:
        if edge.source in adjacency and edge.target in adjacency:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

    visited: set[str] = set()
    components: list[set[str]] = []
    for nid in node_ids:
        if nid not in visited:
            component: set[str] = set()
            stack = [nid]
            while stack:
                curr = stack.pop()
                if curr in visited:
                    continue
                visited.add(curr)
                component.add(curr)
                stack.extend(adjacency[curr] - visited)
            components.append(component)
    return components


def _node_label_map(nodes) -> dict[str, str]:
    """Return {node_id: label} for readable error messages."""
    return {n.id: n.label for n in nodes}


# ---------------------------------------------------------------------------
# Per-script connectivity assertions (reusable)
# ---------------------------------------------------------------------------


def _assert_no_isolated_nodes(script: str, script_name: str) -> None:
    nodes, edges = extract_nodes_with_ranges(script)
    assert nodes, f"{script_name}: parser returned no nodes"

    id_to_label = _node_label_map(nodes)
    nodes_in_edges: set[str] = set()
    for edge in edges:
        nodes_in_edges.add(edge.source)
        nodes_in_edges.add(edge.target)

    isolated = [n for n in nodes if n.id not in nodes_in_edges]
    assert isolated == [], (
        f"{script_name}: {len(isolated)} isolated node(s) with no edges — "
        + ", ".join(f"{n.label!r} (id={n.id!r})" for n in isolated)
    )


def _assert_single_connected_component(script: str, script_name: str) -> None:
    nodes, edges = extract_nodes_with_ranges(script)
    assert nodes, f"{script_name}: parser returned no nodes"

    node_ids = [n.id for n in nodes]
    id_to_label = _node_label_map(nodes)
    components = _connected_components(node_ids, edges)

    assert len(components) == 1, (
        f"{script_name}: expected exactly 1 connected component, "
        f"got {len(components)}.\n"
        + "\n".join(
            f"  Component {i + 1}: "
            + ", ".join(f"{id_to_label.get(nid, nid)!r}" for nid in sorted(comp))
            for i, comp in enumerate(components)
        )
    )


# ---------------------------------------------------------------------------
# fraud.py
# ---------------------------------------------------------------------------


class TestFraudGraphConnectivity:
    """Graph-connectivity tests for the Credit Fraud pipeline script."""

    def test_no_isolated_nodes(self):
        _assert_no_isolated_nodes(FRAUD_SCRIPT, "fraud.py")

    def test_single_connected_component(self):
        _assert_single_connected_component(FRAUD_SCRIPT, "fraud.py")

    def test_every_edge_references_known_nodes(self):
        """Sanity: edges only reference node ids that actually exist."""
        nodes, edges = extract_nodes_with_ranges(FRAUD_SCRIPT)
        known_ids = {n.id for n in nodes}
        for edge in edges:
            assert edge.source in known_ids, (
                f"fraud.py: edge source {edge.source!r} not in node list"
            )
            assert edge.target in known_ids, (
                f"fraud.py: edge target {edge.target!r} not in node list"
            )


# ---------------------------------------------------------------------------
# house_prices.py
# ---------------------------------------------------------------------------


class TestHousePricesGraphConnectivity:
    """Graph-connectivity tests for the House Prices pipeline script."""

    def test_no_isolated_nodes(self):
        _assert_no_isolated_nodes(HOUSE_PRICES_SCRIPT, "house_prices.py")

    def test_single_connected_component(self):
        _assert_single_connected_component(HOUSE_PRICES_SCRIPT, "house_prices.py")

    def test_every_edge_references_known_nodes(self):
        """Sanity: edges only reference node ids that actually exist."""
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_SCRIPT)
        known_ids = {n.id for n in nodes}
        for edge in edges:
            assert edge.source in known_ids, (
                f"house_prices.py: edge source {edge.source!r} not in node list"
            )
            assert edge.target in known_ids, (
                f"house_prices.py: edge target {edge.target!r} not in node list"
            )


# ---------------------------------------------------------------------------
# museums.py
# ---------------------------------------------------------------------------


class TestMuseumsGraphConnectivity:
    """Graph-connectivity tests for the Museum Artworks pipeline script."""

    def test_no_isolated_nodes(self):
        _assert_no_isolated_nodes(MUSEUMS_SCRIPT, "museums.py")

    def test_single_connected_component(self):
        _assert_single_connected_component(MUSEUMS_SCRIPT, "museums.py")

    def test_every_edge_references_known_nodes(self):
        """Sanity: edges only reference node ids that actually exist."""
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_SCRIPT)
        known_ids = {n.id for n in nodes}
        for edge in edges:
            assert edge.source in known_ids, (
                f"museums.py: edge source {edge.source!r} not in node list"
            )
            assert edge.target in known_ids, (
                f"museums.py: edge target {edge.target!r} not in node list"
            )
