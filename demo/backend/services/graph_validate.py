"""
Validate graph JSON for the demo: nodes and edges must form a valid DAG.
Used by compile (to attach validation_errors) and by POST /api/validate-graph.
Schema: nodes = [{ id, type, label, source_range? }], edges = [{ source, target }].
"""

from __future__ import annotations


def _is_dag(node_ids: set[str], edges: list[dict]) -> bool:
    """Return True if the graph has no cycle (topological sort)."""
    in_degree = {n: 0 for n in node_ids}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if t in in_degree and s != t:
            in_degree[t] = in_degree.get(t, 0) + 1
    from collections import deque
    q = deque(n for n in node_ids if in_degree[n] == 0)
    seen = 0
    while q:
        n = q.popleft()
        seen += 1
        for e in edges:
            if e.get("source") == n:
                t = e.get("target")
                if t in in_degree:
                    in_degree[t] -= 1
                    if in_degree[t] == 0:
                        q.append(t)
    return seen == len(node_ids)


def validate_graph_json(nodes: list[dict], edges: list[dict]) -> tuple[bool, list[str]]:
    """
    Verify graph JSON is a correct pipeline DAG.
    Returns (valid, list of error messages). Empty errors => valid.
    """
    errors: list[str] = []

    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        return False, errors
    if not isinstance(edges, list):
        errors.append("edges must be a list")
        return False, errors

    node_ids: set[str] = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            errors.append(f"nodes[{i}] must be an object")
            continue
        nid = n.get("id")
        if nid is None or nid == "":
            errors.append(f"nodes[{i}] missing or empty id")
        elif isinstance(nid, str):
            if nid in node_ids:
                errors.append(f"duplicate node id: {nid!r}")
            node_ids.add(nid)
        else:
            errors.append(f"nodes[{i}].id must be a string")
        if n.get("type") is None and "type" not in n:
            errors.append(f"nodes[{i}] (id={nid!r}) missing type")
        if not isinstance(n.get("label"), str) and "label" not in n:
            errors.append(f"nodes[{i}] (id={nid!r}) missing label")

    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            errors.append(f"edges[{i}] must be an object")
            continue
        s, t = e.get("source"), e.get("target")
        if s is None or t is None:
            errors.append(f"edges[{i}] missing source or target")
        elif s not in node_ids:
            errors.append(f"edges[{i}]: source {s!r} not in nodes")
        elif t not in node_ids:
            errors.append(f"edges[{i}]: target {t!r} not in nodes")

    if not node_ids and not errors:
        errors.append("at least one node required")
    if errors:
        return False, errors

    if not _is_dag(node_ids, edges):
        errors.append("graph must be a DAG (no cycles)")
        return False, errors

    return True, []
