"""
Tests for sem_choose position in the compile graph.

From demo/graph_svgs/medium.svg:
- node_23: Var 'sempipes__choices__hgb_choices__choices' (from sem_choose)
- node_22: apply_with_sem_choose
- node_23 -> node_24, node_22 -> node_24

Semantic flow: sem_choose produces choices passed to apply_with_sem_choose.
So sem_choose must be upstream of apply_with_sem_choose: sem_choose -> apply_with_sem_choose.
"""

import pytest

from services.compile_parse import extract_nodes_with_ranges


def _topo_order(nodes, edges):
    """Return node ids in topological order (roots first)."""
    in_degree = {n.id: 0 for n in nodes}
    for e in edges:
        if e.target in in_degree:
            in_degree[e.target] += 1
    from collections import deque
    q = deque(nid for nid, d in in_degree.items() if d == 0)
    order = []
    while q:
        nid = q.popleft()
        order.append(nid)
        for e in edges:
            if e.source == nid and e.target in in_degree:
                in_degree[e.target] -= 1
                if in_degree[e.target] == 0:
                    q.append(e.target)
    return order


def test_sem_choose_exists_in_medium():
    """Medium script must have a sem_choose node."""
    from pathlib import Path
    code = (Path(__file__).resolve().parent.parent.parent.parent / "pipeline_scripts" / "medium.py").read_text()
    nodes, _ = extract_nodes_with_ranges(code)
    sem_choose_nodes = [n for n in nodes if (n.label or "") == "sem_choose"]
    assert len(sem_choose_nodes) == 1, f"medium must have exactly one sem_choose node. Got: {[n.label for n in nodes]}"


def test_sem_choose_edge_to_apply_with_sem_choose():
    """
    sem_choose must have edge to apply_with_sem_choose (choices= parameter).
    From medium.svg: node_23 (sem_choose choices) feeds into apply_with_sem_choose flow.
    """
    code = """
augmented = some_df
fraud_detector = augmented.skb.apply_with_sem_choose(
    hgb,
    y=fraud_flags,
    choices=sem_choose(name="hgb_choices", max_depth="Common range"),
)
"""
    nodes, edges = extract_nodes_with_ranges(code)
    sem_choose_id = next((n.id for n in nodes if (n.label or "") == "sem_choose"), None)
    apply_id = next((n.id for n in nodes if (n.label or "") == "apply_with_sem_choose"), None)
    assert sem_choose_id, f"must have sem_choose. Nodes: {[n.label for n in nodes]}"
    assert apply_id, f"must have apply_with_sem_choose. Nodes: {[n.label for n in nodes]}"
    edge_pairs = {(e.source, e.target) for e in edges}
    assert (sem_choose_id, apply_id) in edge_pairs, (
        f"sem_choose must have edge to apply_with_sem_choose. Edges: {edge_pairs}"
    )


def test_sem_choose_upstream_of_apply_with_sem_choose_in_topo_order():
    """
    sem_choose must appear before apply_with_sem_choose in topological order
    (sem_choose is upstream / parent in the DAG).
    """
    code = """
augmented = some_df
fraud_detector = augmented.skb.apply_with_sem_choose(
    hgb,
    y=fraud_flags,
    choices=sem_choose(name="hgb_choices", max_depth="Common range"),
)
"""
    nodes, edges = extract_nodes_with_ranges(code)
    runnable = [n for n in nodes if (n.type or "").lower() in ("input", "operator")]
    order = _topo_order(runnable, edges)
    sem_choose_id = next((n.id for n in runnable if (n.label or "") == "sem_choose"), None)
    apply_id = next((n.id for n in runnable if (n.label or "") == "apply_with_sem_choose"), None)
    assert sem_choose_id and apply_id
    sc_idx = order.index(sem_choose_id)
    ac_idx = order.index(apply_id)
    assert sc_idx < ac_idx, (
        f"sem_choose must be upstream of apply_with_sem_choose (topo order). "
        f"sem_choose at {sc_idx}, apply at {ac_idx}. Order: {order}"
    )


def test_medium_sem_choose_position_matches_svg():
    """
    Medium pipeline: sem_choose -> apply_with_sem_choose must exist and
    sem_choose must be upstream. Matches flow from demo/graph_svgs/medium.svg.
    """
    from pathlib import Path
    code = (Path(__file__).resolve().parent.parent.parent.parent / "pipeline_scripts" / "medium.py").read_text()
    nodes, edges = extract_nodes_with_ranges(code)
    runnable = [n for n in nodes if (n.type or "").lower() in ("input", "operator")]
    edge_pairs = {(e.source, e.target) for e in edges}
    order = _topo_order(runnable, edges)

    sem_choose_id = next((n.id for n in runnable if (n.label or "") == "sem_choose"), None)
    apply_id = next((n.id for n in runnable if (n.label or "") == "apply_with_sem_choose"), None)
    assert sem_choose_id and apply_id, f"medium must have sem_choose and apply_with_sem_choose. Nodes: {[n.label for n in runnable]}"

    assert (sem_choose_id, apply_id) in edge_pairs, (
        f"medium: sem_choose -> apply_with_sem_choose required (from SVG). Edges: {edge_pairs}"
    )

    sc_idx = order.index(sem_choose_id)
    ac_idx = order.index(apply_id)
    assert sc_idx < ac_idx, (
        f"medium: sem_choose must be upstream of apply_with_sem_choose. "
        f"sem_choose at {sc_idx}, apply at {ac_idx}"
    )
