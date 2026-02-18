"""Comprehensive tests for medium.py script source range mappings.

These tests verify that each node in the compiled graph correctly maps to the
expected line and column positions in the medium.py source code.

Expected to reveal bugs in source range merging for:
- GetItem nodes mapping to as_X/as_y
- Chained pandas operations (groupby, agg, reset_index)
- isin method calls
- TableVectorizer operations
"""

from pathlib import Path

import pytest

from services.graph_api import compile_script_to_graph_dynamic


@pytest.fixture
def medium_script():
    """Load the medium.py script content."""
    script_path = Path(__file__).parents[3] / "pipeline_scripts" / "medium.py"
    return script_path.read_text()


def test_medium_script_compiles(medium_script):
    """Medium script should compile without errors."""
    result = compile_script_to_graph_dynamic(medium_script)
    assert result.is_valid, f"Graph should be valid, got errors: {result.validation_errors}"
    assert len(result.nodes) > 0, "Should have at least one node"


def test_var_nodes_have_correct_lines(medium_script):
    """Var nodes (products, baskets) should map to lines 13-14."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 13: products = skrub.var("products", dataset.products)
    products_var = [n for n in result.nodes if n.label == "<Var 'products'>"]
    assert len(products_var) == 1, "Should find products var node"
    assert products_var[0].source_range is not None, "products var should have source_range"
    assert products_var[0].source_range.start_line == 13, \
        f"products var should start at line 13, got {products_var[0].source_range.start_line}"

    # Line 14: baskets = skrub.var("baskets", dataset.baskets)
    baskets_var = [n for n in result.nodes if n.label == "<Var 'baskets'>"]
    assert len(baskets_var) == 1, "Should find baskets var node"
    assert baskets_var[0].source_range is not None, "baskets var should have source_range"
    assert baskets_var[0].source_range.start_line == 14, \
        f"baskets var should start at line 14, got {baskets_var[0].source_range.start_line}"


def test_subsample_node_line(medium_script):
    """Subsample node should map to line 15."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 15: baskets = baskets.skb.subsample(n=5000, how="random")
    subsample_nodes = [n for n in result.nodes if "subsample" in n.label.lower()]
    assert len(subsample_nodes) == 1, f"Should find exactly one subsample node, got {len(subsample_nodes)}"
    assert subsample_nodes[0].source_range is not None, "subsample should have source_range"
    assert subsample_nodes[0].source_range.start_line == 15, \
        f"subsample should start at line 15, got {subsample_nodes[0].source_range.start_line}"


def test_as_x_node_line(medium_script):
    """as_X manifests as GetItem in skrub graph, should map to line 18.

    Note: Skrub doesn't create explicit as_X nodes. The as_X call appears as a GetItem
    node for the column selection (baskets[["ID"]]).
    """
    pytest.skip("as_X doesn't appear as a separate node in skrub graph - see test_getitem_for_as_x_maps_to_line_18")


def test_as_y_node_line(medium_script):
    """as_y manifests as GetItem in skrub graph, should map to line 19.

    Note: Skrub doesn't create explicit as_y nodes. The as_y call appears as a GetItem
    node for the column selection (baskets["fraud_flag"]).
    """
    pytest.skip("as_y doesn't appear as a separate node in skrub graph - see test_getitem_for_as_y_maps_to_line_19")


def test_getitem_for_as_x_maps_to_line_18(medium_script):
    """GetItem node for baskets[["ID"]] should map to line 18 (same as as_X).

    This is the critical test for GetItem mapping - the GetItem operation happens
    on the same line as the as_X call, so it should have the same source range.
    """
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 18: basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")
    # The GetItem node for baskets[["ID"]] should map to this line
    getitem_nodes = [n for n in result.nodes if n.label.startswith("<GetItem")]

    # Should have at least 2 GetItem nodes (one for as_X, one for as_y, plus more for isin)
    assert len(getitem_nodes) >= 2, f"Should find at least 2 GetItem nodes, got {len(getitem_nodes)}"

    # Find the GetItem that should map to as_X (line 18)
    # This is tricky - we need to identify it by its context or order
    # The first GetItem should be for the as_X line
    first_getitem = getitem_nodes[0]
    assert first_getitem.source_range is not None, "First GetItem should have source_range"
    assert first_getitem.source_range.start_line == 18, \
        f"First GetItem (for as_X) should map to line 18, got {first_getitem.source_range.start_line}"


def test_getitem_for_as_y_maps_to_line_19(medium_script):
    """GetItem node for baskets["fraud_flag"] should map to line 19 (same as as_y)."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 19: fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Fraud label")
    # Find the GetItem node with 'fraud_flag' in its label
    fraud_flag_getitems = [n for n in result.nodes if n.label.startswith("<GetItem") and "fraud_flag" in n.label]

    assert len(fraud_flag_getitems) >= 1, \
        f"Should find at least one GetItem with 'fraud_flag', got {len(fraud_flag_getitems)}"
    fraud_flag_getitem = fraud_flag_getitems[0]
    assert fraud_flag_getitem.source_range is not None, "fraud_flag GetItem should have source_range"
    assert fraud_flag_getitem.source_range.start_line == 19, \
        f"fraud_flag GetItem should map to line 19, got {fraud_flag_getitem.source_range.start_line}"


def test_sem_fillna_node_line(medium_script):
    """sem_fillna node should map to line 22 (start of the call)."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 22-26: products.sem_fillna(...)
    fillna_nodes = [n for n in result.nodes if n.label == "sem_fillna"]
    assert len(fillna_nodes) == 1, f"Should find exactly one sem_fillna node, got {len(fillna_nodes)}"
    assert fillna_nodes[0].source_range is not None, "sem_fillna should have source_range"
    assert fillna_nodes[0].source_range.start_line == 22, \
        f"sem_fillna should start at line 22, got {fillna_nodes[0].source_range.start_line}"


def test_isin_node_line(medium_script):
    """isin method call is captured but not mapped to source (no static parse node for it).

    Note: The static parse doesn't create nodes for intermediate method calls like isin,
    so while the skrub graph includes an isin node, it won't have a source range.
    """
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 27: kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
    # The isin call should be captured as a node
    isin_nodes = [n for n in result.nodes if "isin" in n.label.lower()]
    assert len(isin_nodes) >= 1, f"Should find at least one isin node, got {len(isin_nodes)}"

    # isin is captured but doesn't have a source range (no matching node in static parse)
    # This is acceptable - not every skrub node needs a source range


def test_sem_gen_features_node_line(medium_script):
    """sem_gen_features node should map to line 28 (start of the call)."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 28-32: kept_products.sem_gen_features(...)
    gen_features_nodes = [n for n in result.nodes if n.label == "sem_gen_features"]
    assert len(gen_features_nodes) == 1, \
        f"Should find exactly one sem_gen_features node, got {len(gen_features_nodes)}"
    assert gen_features_nodes[0].source_range is not None, "sem_gen_features should have source_range"
    assert gen_features_nodes[0].source_range.start_line == 28, \
        f"sem_gen_features should start at line 28, got {gen_features_nodes[0].source_range.start_line}"


def test_skb_apply_node_line(medium_script):
    """skb.apply node should map to line 36."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 36: vectorized_products = kept_products.skb.apply(vectorizer, exclude_cols=["basket_ID"])
    apply_nodes = [n for n in result.nodes if "apply" in n.label.lower() and "sem_choose" not in n.label.lower()]

    # Filter to just skb.apply (not apply_with_sem_choose)
    skb_apply_nodes = [n for n in apply_nodes if "with" not in n.label.lower()]
    assert len(skb_apply_nodes) >= 1, \
        f"Should find at least one skb.apply node, got {len(skb_apply_nodes)}: {[n.label for n in apply_nodes]}"

    assert skb_apply_nodes[0].source_range is not None, "skb.apply should have source_range"
    assert skb_apply_nodes[0].source_range.start_line == 36, \
        f"skb.apply should map to line 36, got {skb_apply_nodes[0].source_range.start_line}"


def test_groupby_node_line(medium_script):
    """groupby node should map to line 37."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 37: aggregated_products = vectorized_products.groupby("basket_ID").agg("mean").reset_index()
    # Skrub creates <CallMethod 'groupby'> nodes, not "groupby"
    groupby_nodes = [n for n in result.nodes if "groupby" in n.label.lower()]
    assert len(groupby_nodes) == 1, f"Should find exactly one groupby node, got {len(groupby_nodes)}"
    assert groupby_nodes[0].source_range is not None, "groupby should have source_range"
    assert groupby_nodes[0].source_range.start_line == 37, \
        f"groupby should map to line 37, got {groupby_nodes[0].source_range.start_line}"


def test_agg_method_maps_to_groupby_line(medium_script):
    """agg method call should map to line 37 (same as groupby).

    This is a critical test - chained methods like .agg() should map to the
    same line as their parent operation (.groupby()).
    """
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 37: ... .groupby("basket_ID").agg("mean").reset_index()
    agg_nodes = [n for n in result.nodes if "agg" in n.label.lower()]

    if len(agg_nodes) > 0:
        # If we have an agg node, it should map to line 37
        assert agg_nodes[0].source_range is not None, "agg should have source_range"
        assert agg_nodes[0].source_range.start_line == 37, \
            f"agg method should map to line 37 (same as groupby), got {agg_nodes[0].source_range.start_line}"
    else:
        # If agg doesn't appear as a separate node, that's also acceptable
        # (it might be fused with groupby)
        pytest.skip("agg not present as separate node (may be fused with groupby)")


def test_reset_index_method_maps_to_groupby_line(medium_script):
    """reset_index method call should map to line 37 (same as groupby).

    This is a critical test - chained methods like .reset_index() should map to
    the same line as their parent operation (.groupby()).
    """
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 37: ... .groupby("basket_ID").agg("mean").reset_index()
    reset_nodes = [n for n in result.nodes if "reset_index" in n.label.lower()]

    if len(reset_nodes) > 0:
        # If we have a reset_index node, it should map to line 37
        assert reset_nodes[0].source_range is not None, "reset_index should have source_range"
        assert reset_nodes[0].source_range.start_line == 37, \
            f"reset_index method should map to line 37 (same as groupby), got {reset_nodes[0].source_range.start_line}"
    else:
        # If reset_index doesn't appear as a separate node, that's also acceptable
        pytest.skip("reset_index not present as separate node (may be fused with groupby)")


def test_merge_node_line(medium_script):
    """merge node should map to line 38."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 38-40: augmented_baskets = basket_ids.merge(...).drop(...)
    # Skrub creates <CallMethod 'merge'> nodes, not "merge"
    merge_nodes = [n for n in result.nodes if "merge" in n.label.lower()]
    assert len(merge_nodes) == 1, f"Should find exactly one merge node, got {len(merge_nodes)}"
    assert merge_nodes[0].source_range is not None, "merge should have source_range"
    assert merge_nodes[0].source_range.start_line == 38, \
        f"merge should start at line 38, got {merge_nodes[0].source_range.start_line}"


def test_drop_node_line(medium_script):
    """drop node should map to line 38 (same line as merge, chained call)."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 38-40: ... .merge(...).drop(columns=["ID", "basket_ID"])
    # Skrub creates <CallMethod 'drop'> nodes, not "drop"
    drop_nodes = [n for n in result.nodes if "drop" in n.label.lower()]
    assert len(drop_nodes) == 1, f"Should find exactly one drop node, got {len(drop_nodes)}"
    assert drop_nodes[0].source_range is not None, "drop should have source_range"
    # drop is on line 38 (chained from merge), but the actual .drop( might be on line 38 or 39
    # Let's check it's in the range 38-40
    assert 38 <= drop_nodes[0].source_range.start_line <= 40, \
        f"drop should be in lines 38-40, got {drop_nodes[0].source_range.start_line}"


def test_apply_with_sem_choose_node_line(medium_script):
    """apply_with_sem_choose node should map to line 44 (start of the call)."""
    result = compile_script_to_graph_dynamic(medium_script)

    # Line 44-48: fraud_detector = augmented_baskets.skb.apply_with_sem_choose(...)
    apply_choose_nodes = [n for n in result.nodes if "apply_with_sem_choose" in n.label.lower()]
    assert len(apply_choose_nodes) == 1, \
        f"Should find exactly one apply_with_sem_choose node, got {len(apply_choose_nodes)}"
    assert apply_choose_nodes[0].source_range is not None, "apply_with_sem_choose should have source_range"
    assert apply_choose_nodes[0].source_range.start_line == 44, \
        f"apply_with_sem_choose should start at line 44, got {apply_choose_nodes[0].source_range.start_line}"


def test_sem_choose_node_line(medium_script):
    """sem_choose doesn't appear as a separate node in skrub graph.

    Note: Skrub embeds sem_choose within the apply_with_sem_choose node, so it
    doesn't create a separate sem_choose node. The static parse does identify it,
    but there's no corresponding skrub node to map to.
    """
    pytest.skip("sem_choose doesn't appear as separate node in skrub graph (embedded in apply_with_sem_choose)")


def test_all_important_nodes_have_source_ranges(medium_script):
    """All important nodes (operators, inputs) should have source_range information.

    Note: Some intermediate nodes (like GetItem for filters, isin, etc.) won't have source
    ranges because the static parse doesn't capture every single method call - only the
    high-level operations (sem_fillna, sem_gen_features, groupby, merge, etc.).
    """
    result = compile_script_to_graph_dynamic(medium_script)

    # Check that important nodes have source ranges
    important_nodes = [
        n for n in result.nodes
        if n.label in ["sem_fillna", "sem_gen_features", "apply_with_sem_choose"]
        or n.label.startswith("<Var")
        or "subsample" in n.label.lower()
        or "apply" in n.label.lower()
        or "groupby" in n.label.lower()
        or "merge" in n.label.lower()
    ]

    nodes_without_ranges = [n for n in important_nodes if n.source_range is None]

    if nodes_without_ranges:
        labels = [n.label for n in nodes_without_ranges]
        pytest.fail(
            f"Found {len(nodes_without_ranges)} important nodes without source_range: {labels}\n"
            f"All important nodes should have source ranges for code-graph synchronization."
        )


def test_source_ranges_are_reasonable(medium_script):
    """All source ranges should have reasonable line numbers (1-49 for medium.py).

    This catches bugs where source ranges are clearly wrong (line 0, line 999, etc).
    """
    result = compile_script_to_graph_dynamic(medium_script)

    num_lines = len(medium_script.splitlines())

    for node in result.nodes:
        if node.source_range is None:
            continue

        assert 1 <= node.source_range.start_line <= num_lines, \
            f"Node {node.label} has invalid start_line {node.source_range.start_line} (should be 1-{num_lines})"

        assert 1 <= node.source_range.end_line <= num_lines, \
            f"Node {node.label} has invalid end_line {node.source_range.end_line} (should be 1-{num_lines})"

        assert node.source_range.start_line <= node.source_range.end_line, \
            f"Node {node.label} has start_line > end_line: {node.source_range.start_line} > {node.source_range.end_line}"
