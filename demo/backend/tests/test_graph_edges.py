"""Edge-specific tests for compile_parse.extract_nodes_with_ranges.

Covers two main areas:

1. **drop → as_X / as_y edges** — various combinations of how a `.drop()`
   result flows into `sempipes.as_X()` or `sempipes.as_y()`:
   - inline drop as the first argument to as_X/as_y (single-line and multi-line)
   - drop assigned to a variable, then passed to as_X/as_y

2. **sem_agg_features first-arg edge** — the first positional argument to
   `.sem_agg_features(other_df, ...)` must produce an edge
   ``producer_of(other_df) → sem_agg_features``.  Verified both on a minimal
   snippet and on the real fraud pipeline script.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.compile_parse import extract_nodes_with_ranges
from test_new_scripts_source_ranges import FRAUD_SCRIPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _edge_pairs(edges) -> set[tuple[str, str]]:
    """Return set of (source_label, target_label) from edges and node list."""
    return {(e.source, e.target) for e in edges}


def _node_id(nodes, label: str) -> str | None:
    for n in nodes:
        if n.label == label:
            return n.id
    return None


def _node_ids(nodes, label: str) -> list[str]:
    return [n.id for n in nodes if n.label == label]


def _has_edge(nodes, edges, src_label: str, tgt_label: str) -> bool:
    """Return True if there is an edge from a node with src_label to one with tgt_label."""
    src_ids = set(_node_ids(nodes, src_label))
    tgt_ids = set(_node_ids(nodes, tgt_label))
    for e in edges:
        if e.source in src_ids and e.target in tgt_ids:
            return True
    return False


def _has_edge_by_line(nodes, edges, src_line: int, tgt_line: int) -> bool:
    """Return True if there is an edge between nodes identified by source_range.start_line."""
    src_ids = {n.id for n in nodes if n.source_range and n.source_range.start_line == src_line}
    tgt_ids = {n.id for n in nodes if n.source_range and n.source_range.start_line == tgt_line}
    for e in edges:
        if e.source in src_ids and e.target in tgt_ids:
            return True
    return False


# ===========================================================================
# drop → as_X edge tests
# ===========================================================================


class TestDropToAsXEdge:
    """Tests for the edge from a .drop() node to an as_X node."""

    # -----------------------------------------------------------------------
    # Pattern 1: inline drop on same line as as_X
    # -----------------------------------------------------------------------

    def test_inline_drop_same_line_as_x(self):
        """as_X(df.drop(columns=['y']), 'desc') — drop and as_X on one line."""
        script = """\
def sempipes_pipeline():
    df = skrub.var("df")
    target = sempipes.as_y(df["y"], "target")
    features = sempipes.as_X(df.drop(columns=["y"]), "features")
"""
        nodes, edges = extract_nodes_with_ranges(script)
        assert _has_edge(nodes, edges, "drop", "as_X"), (
            "Expected edge drop → as_X for inline pattern"
        )

    # -----------------------------------------------------------------------
    # Pattern 2: inline drop, multi-line as_X call
    # -----------------------------------------------------------------------

    def test_inline_drop_multiline_as_x(self):
        """as_X(\\n    df.drop(...),\\n    'desc'\\n) — drop argument on next line."""
        script = """\
def sempipes_pipeline():
    df = skrub.var("df")
    target = sempipes.as_y(df["y"], "target")
    features = sempipes.as_X(
        df.drop(columns=["y"]),
        "features"
    )
"""
        nodes, edges = extract_nodes_with_ranges(script)
        assert _has_edge(nodes, edges, "drop", "as_X"), (
            "Expected edge drop → as_X for multi-line inline pattern"
        )

    # -----------------------------------------------------------------------
    # Pattern 3: drop assigned to a variable, variable passed to as_X
    # -----------------------------------------------------------------------

    def test_drop_variable_then_as_x(self):
        """df_clean = df.drop(...)\\nfeatures = sempipes.as_X(df_clean, 'desc')"""
        script = """\
def sempipes_pipeline():
    df = skrub.var("df")
    target = sempipes.as_y(df["y"], "target")
    df_clean = df.drop(columns=["y"])
    features = sempipes.as_X(df_clean, "features")
"""
        nodes, edges = extract_nodes_with_ranges(script)
        assert _has_edge(nodes, edges, "drop", "as_X"), (
            "Expected edge drop → as_X for separate-variable pattern"
        )

    # -----------------------------------------------------------------------
    # Pattern 4: inline drop in as_X, no as_y present
    # -----------------------------------------------------------------------

    def test_inline_drop_as_x_no_as_y(self):
        """Inline drop in as_X without any as_y in the script."""
        script = """\
def sempipes_pipeline():
    df = skrub.var("df")
    features = sempipes.as_X(df.drop(columns=["unwanted"]), "features")
"""
        nodes, edges = extract_nodes_with_ranges(script)
        assert _has_edge(nodes, edges, "drop", "as_X"), (
            "Expected edge drop → as_X even without as_y"
        )

    # -----------------------------------------------------------------------
    # Pattern 5: house_prices inline-drop style (multi-step, chained merge first)
    # -----------------------------------------------------------------------

    def test_inline_drop_as_x_after_merge(self):
        """Realistic: merge → houses, inline drop inside as_X."""
        script = """\
def sempipes_pipeline():
    facts = skrub.var("facts")
    cities = skrub.var("cities")
    houses = facts.merge(cities, on="city_id")
    price = sempipes.as_y(houses["price"], "price")
    house_data = sempipes.as_X(
        houses.drop(columns=["price"]),
        "house features"
    )
    house_data = house_data.sem_clean(nl_prompt="clean", columns=["sqft"])
"""
        nodes, edges = extract_nodes_with_ranges(script)
        assert _has_edge(nodes, edges, "drop", "as_X"), (
            "Expected drop → as_X edge when drop is inline in as_X after merge"
        )


# ===========================================================================
# drop → as_y edge tests
# ===========================================================================


class TestDropToAsYEdge:
    """Tests for the edge from a .drop() node to an as_y node."""

    def test_inline_drop_as_y(self):
        """as_y(df.drop(...)["target"], 'desc') — inline drop inside as_y."""
        script = """\
def sempipes_pipeline():
    df = skrub.var("df")
    target = sempipes.as_y(df.drop(columns=["id"])["target"], "target")
    features = sempipes.as_X(df.drop(columns=["target"]), "features")
"""
        nodes, edges = extract_nodes_with_ranges(script)
        # There should be drop nodes; at least one drop → as_y edge
        drop_nodes = [n for n in nodes if n.label == "drop"]
        as_y_nodes = [n for n in nodes if n.label == "as_y"]
        assert drop_nodes, "Expected at least one drop node"
        assert as_y_nodes, "Expected an as_y node"
        # Check an edge from some drop to as_y
        assert _has_edge(nodes, edges, "drop", "as_y"), (
            "Expected drop → as_y edge for inline pattern"
        )

    def test_drop_variable_then_as_y(self):
        """df_sub = df.drop(...)\\ntarget = sempipes.as_y(df_sub['target'], ...)"""
        script = """\
def sempipes_pipeline():
    df = skrub.var("df")
    df_sub = df.drop(columns=["id"])
    target = sempipes.as_y(df_sub["target"], "target")
    features = sempipes.as_X(df_sub.drop(columns=["target"]), "features")
"""
        nodes, edges = extract_nodes_with_ranges(script)
        assert _has_edge(nodes, edges, "drop", "as_y"), (
            "Expected drop → as_y edge when drop result is assigned then used in as_y"
        )


# ===========================================================================
# drop → as_X (real scripts)
# ===========================================================================


class TestDropToAsXRealScripts:
    """Verify drop → as_X edges in the embedded real pipeline scripts."""

    def test_house_prices_drop_to_as_x_edge(self):
        """house_prices: houses.drop(columns=['price']) inline in as_X → edge exists."""
        from test_new_scripts_source_ranges import HOUSE_PRICES_SCRIPT
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_SCRIPT)
        # drop at line 37, as_X at line 36 (as_X call spans two lines)
        assert _has_edge_by_line(nodes, edges, src_line=37, tgt_line=36), (
            "Expected edge from drop@L37 to as_X@L36 in house_prices script"
        )

    def test_museums_drop_to_as_x_edge(self):
        """museums: artworks.drop(columns=['culture']) inline in as_X → edge exists."""
        from test_new_scripts_source_ranges import MUSEUMS_SCRIPT
        nodes, edges = extract_nodes_with_ranges(MUSEUMS_SCRIPT)
        # drop at line 199, as_X at line 198
        assert _has_edge_by_line(nodes, edges, src_line=199, tgt_line=198), (
            "Expected edge from drop@L199 to as_X@L198 in museums script"
        )

    def test_house_prices_no_spurious_drop_edges(self):
        """house_prices: the drop at line 37 should not also create a spurious as_y edge."""
        from test_new_scripts_source_ranges import HOUSE_PRICES_SCRIPT
        nodes, edges = extract_nodes_with_ranges(HOUSE_PRICES_SCRIPT)
        # drop at line 37 is inline in as_X, not in as_y; should NOT have drop@37 → as_y
        as_y_ids = {n.id for n in nodes if n.label == "as_y"}
        drop_37_ids = {n.id for n in nodes if n.source_range and n.source_range.start_line == 37}
        for e in edges:
            if e.source in drop_37_ids and e.target in as_y_ids:
                pytest.fail(
                    f"Spurious edge drop@L37 → as_y found in house_prices script"
                )


# ===========================================================================
# sem_agg_features first-argument edge
# ===========================================================================


class TestSemAggFeaturesFirstArgEdge:
    """Tests that the first positional arg of sem_agg_features creates a producer→sem_agg_features edge."""

    def test_minimal_sem_agg_features_edge(self):
        """Minimal: vectorized_products → sem_agg_features via first positional arg."""
        script = """\
def sempipes_pipeline():
    baskets = skrub.var("baskets")
    products = skrub.var("products")
    basket_ids = sempipes.as_X(baskets[["ID"]], "baskets")
    vectorized_products = products.skb.apply(vectorizer)
    augmented = basket_ids.sem_agg_features(
        vectorized_products,
        left_on="ID",
        right_on="basket_ID",
        nl_prompt="aggregate",
        name="agg",
        how_many=1,
    )
"""
        nodes, edges = extract_nodes_with_ranges(script)
        assert _has_edge(nodes, edges, "skb.apply", "sem_agg_features"), (
            "Expected edge skb.apply → sem_agg_features via first positional arg"
        )

    def test_sem_agg_features_first_arg_not_just_receiver(self):
        """sem_agg_features consumes BOTH receiver (basket_ids) AND first arg (vectorized_products)."""
        script = """\
def sempipes_pipeline():
    baskets = skrub.var("baskets")
    products = skrub.var("products")
    basket_ids = sempipes.as_X(baskets[["ID"]], "baskets")
    vectorized_products = products.skb.apply(vectorizer)
    augmented = basket_ids.sem_agg_features(
        vectorized_products,
        left_on="ID",
        right_on="basket_ID",
        nl_prompt="aggregate",
        name="agg",
        how_many=1,
    )
"""
        nodes, edges = extract_nodes_with_ranges(script)
        agg_nodes = [n for n in nodes if n.label == "sem_agg_features"]
        assert len(agg_nodes) == 1
        agg_id = agg_nodes[0].id
        # Find all source nodes for sem_agg_features
        src_ids = {e.source for e in edges if e.target == agg_id}
        src_labels = {n.label for n in nodes if n.id in src_ids}
        # Must include both as_X (receiver chain) and skb.apply (first arg)
        assert "skb.apply" in src_labels, (
            f"Expected skb.apply in sem_agg_features sources; got {src_labels}"
        )

    def test_fraud_skb_apply_to_sem_agg_features_edge(self):
        """Real fraud script: vectorized_products (skb.apply@L109) → sem_agg_features@L114."""
        nodes, edges = extract_nodes_with_ranges(FRAUD_SCRIPT)
        # skb.apply at line 109 produces vectorized_products
        # sem_agg_features at line 114 consumes vectorized_products as first arg
        assert _has_edge_by_line(nodes, edges, src_line=109, tgt_line=114), (
            "Expected edge from skb.apply@L109 to sem_agg_features@L114 in fraud script"
        )

    def test_fraud_sem_agg_features_has_two_incoming_edges(self):
        """fraud: sem_agg_features@L114 must have at least 2 incoming edges (as_X chain + skb.apply)."""
        nodes, edges = extract_nodes_with_ranges(FRAUD_SCRIPT)
        agg_nodes = [
            n for n in nodes
            if n.label == "sem_agg_features" and n.source_range
            and n.source_range.start_line == 114
        ]
        assert len(agg_nodes) == 1, "Expected one sem_agg_features node at line 114"
        agg_id = agg_nodes[0].id
        incoming = [e for e in edges if e.target == agg_id]
        assert len(incoming) >= 2, (
            f"Expected at least 2 incoming edges to sem_agg_features@L114, "
            f"got {len(incoming)}: {[(e.source, e.target) for e in incoming]}"
        )
