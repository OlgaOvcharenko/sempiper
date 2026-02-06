"""
Dedicated tests for subsample -> as_X / as_y edges in compile output.

as_X and as_y consume from the output of skb.subsample (e.g. baskets = baskets.skb.subsample).
The compile must produce edges subsample -> as_X and subsample -> as_y so the graph
shows as_X/as_y below subsample.

Minimal snippets reproduce specific failure modes:
- single_line: Pass 1 handles; fails if var_producer/consumes broken
- multiline: requires line_context in _extract_produces_consumes; fails with single-line search
- alias: requires _resolve_producers in Pass 2; fails with var_producer.get(var) only
"""

import pytest

from services.compile_parse import extract_nodes_with_ranges


def _assert_subsample_to_as_x_edge(nodes, edges, msg=""):
    """Helper: assert subsample->as_X edge exists."""
    subsample_id = next((n.id for n in nodes if (n.label or "") == "skb.subsample"), None)
    as_x_id = next((n.id for n in nodes if (n.label or "").lower() == "as_x"), None)
    assert subsample_id and as_x_id, f"nodes: {[(n.id, n.label) for n in nodes]}"
    edge_pairs = {(e.source, e.target) for e in edges}
    assert (subsample_id, as_x_id) in edge_pairs, (
        f"{msg}must have edge {subsample_id}->{as_x_id}. Edges: {edge_pairs}"
    )


def _assert_subsample_to_as_y_edge(nodes, edges, msg=""):
    """Helper: assert subsample->as_y edge exists."""
    subsample_id = next((n.id for n in nodes if (n.label or "") == "skb.subsample"), None)
    as_y_id = next((n.id for n in nodes if (n.label or "").lower() == "as_y"), None)
    assert subsample_id and as_y_id, f"nodes: {[(n.id, n.label) for n in nodes]}"
    edge_pairs = {(e.source, e.target) for e in edges}
    assert (subsample_id, as_y_id) in edge_pairs, (
        f"{msg}must have edge {subsample_id}->{as_y_id}. Edges: {edge_pairs}"
    )


# Minimal snippets that reproduce specific failure modes (each ~4-6 lines)
MINIMAL_SNIPPETS = {
    "single_line_as_x": (
        "baskets = skrub.var(\"baskets\", data)\n"
        "baskets = baskets.skb.subsample(n=100)\n"
        "x = sempipes.as_X(baskets[[\"id\"]], \"X\")"
    ),
    "single_line_as_y": (
        "baskets = skrub.var(\"baskets\", data)\n"
        "baskets = baskets.skb.subsample(n=100)\n"
        "y = sempipes.as_y(baskets[\"label\"], \"y\")"
    ),
    "both_as_x_as_y": (
        "baskets = skrub.var(\"baskets\", data)\n"
        "baskets = baskets.skb.subsample(n=100)\n"
        "x = sempipes.as_X(baskets[[\"id\"]], \"X\")\n"
        "y = sempipes.as_y(baskets[\"label\"], \"y\")"
    ),
    "multiline_as_x": (
        "baskets = skrub.var(\"baskets\", data)\n"
        "baskets = baskets.skb.subsample(n=100)\n"
        "basket_ids = sempipes.as_X(\n"
        "    baskets[[\"ID\"]], \"Shopping baskets\")"
    ),
    "alias_as_x": (
        "baskets = skrub.var(\"baskets\", data)\n"
        "baskets = baskets.skb.subsample(n=100)\n"
        "b = baskets\n"
        "x = sempipes.as_X(b[[\"id\"]], \"X\")"
    ),
    "extra_line_shifts_numbers": (
        "# extra line shifts line numbers\n\n"
        "baskets = skrub.var(\"baskets\", data)\n"
        "baskets = baskets.skb.subsample(n=100)\n"
        "x = sempipes.as_X(baskets[[\"id\"]], \"X\")"
    ),
}


@pytest.mark.parametrize(
    "name,code,expected",
    [
        ("single_line_as_x", MINIMAL_SNIPPETS["single_line_as_x"], ["as_x"]),
        ("single_line_as_y", MINIMAL_SNIPPETS["single_line_as_y"], ["as_y"]),
        ("both_as_x_as_y", MINIMAL_SNIPPETS["both_as_x_as_y"], ["as_x", "as_y"]),
        ("multiline_as_x", MINIMAL_SNIPPETS["multiline_as_x"], ["as_x"]),
        ("alias_as_x", MINIMAL_SNIPPETS["alias_as_x"], ["as_x"]),
        ("extra_line_shifts_numbers", MINIMAL_SNIPPETS["extra_line_shifts_numbers"], ["as_x"]),
    ],
)
def test_minimal_snippet_has_subsample_edges(name, code, expected):
    """Each minimal snippet must produce subsample->as_X and/or subsample->as_y edges."""
    nodes, edges = extract_nodes_with_ranges(code)
    if "as_x" in expected:
        _assert_subsample_to_as_x_edge(nodes, edges, msg=f"[{name}] ")
    if "as_y" in expected:
        _assert_subsample_to_as_y_edge(nodes, edges, msg=f"[{name}] ")


def test_multiline_fails_without_line_context():
    """
    Regression: multiline as_X fails when _extract_produces_consumes searches only
    the single line (first arg on next line). Proves line_context fix is required.
    """
    from services.compile_parse import _extract_produces_consumes

    line = "basket_ids = sempipes.as_X("
    line_context = "basket_ids = sempipes.as_X(\n    baskets[[\"ID\"]], \"Shopping baskets\")"
    call_start = 21  # 0-based column of "a" in "as_X"

    # Broken: search only line -> no match, consumes empty
    _, consumes_line_only = _extract_produces_consumes(
        line, "as_X", "input", call_start, line_context=None
    )
    assert consumes_line_only == [], "single-line search must yield empty consumes for multiline call"

    # Fixed: search line_context -> finds baskets
    _, consumes_with_ctx = _extract_produces_consumes(
        line, "as_X", "input", call_start, line_context=line_context
    )
    assert consumes_with_ctx == ["baskets"], "line_context search must find baskets"


def test_pass2_resolve_producers_needed_for_alias():
    """
    Regression: as_X(b[...]) where b=baskets needs _resolve_producers in Pass 2.
    var_producer.get("b") is None; _resolve_producers("b", ...) follows depends_on -> baskets.
    """
    code = MINIMAL_SNIPPETS["alias_as_x"]
    nodes, edges = extract_nodes_with_ranges(code)
    _assert_subsample_to_as_x_edge(nodes, edges)


def test_medium_like_structure_subsample_to_as_x_as_y():
    """Medium-like structure (products, baskets, subsample, as_X, as_y) must have both edges."""
    code = """# line 1
# line 2
# line 3
import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)
baskets = baskets.skb.subsample(n=5000, how="random")

# X and y from baskets
basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Fraud label")
"""
    nodes, edges = extract_nodes_with_ranges(code)
    _assert_subsample_to_as_x_edge(nodes, edges, msg="medium-like ")
    _assert_subsample_to_as_y_edge(nodes, edges, msg="medium-like ")
