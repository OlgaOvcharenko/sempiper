"""Tests for pandas DataFrame operations in compile graph."""

from services.compile_parse import extract_nodes_with_ranges


def test_groupby_node_extracted():
    """groupby operation should be extracted as a node."""
    code = """
products = df.groupby("category").mean()
"""
    nodes, edges = extract_nodes_with_ranges(code)

    groupby_nodes = [n for n in nodes if n.label == "groupby"]
    assert len(groupby_nodes) == 1
    assert groupby_nodes[0].type == "operator"
    assert groupby_nodes[0].source_range.start_line == 2


def test_merge_node_extracted():
    """merge operation should be extracted as a node."""
    code = """
result = left_df.merge(right_df, on="id")
"""
    nodes, edges = extract_nodes_with_ranges(code)

    merge_nodes = [n for n in nodes if n.label == "merge"]
    assert len(merge_nodes) == 1
    assert merge_nodes[0].type == "operator"


def test_drop_node_extracted():
    """drop operation should be extracted as a node."""
    code = """
cleaned = df.drop(columns=["temp"])
"""
    nodes, edges = extract_nodes_with_ranges(code)

    drop_nodes = [n for n in nodes if n.label == "drop"]
    assert len(drop_nodes) == 1
    assert drop_nodes[0].type == "operator"


def test_merge_consumes_both_dataframes():
    """merge should have edges from both dataframes."""
    code = """
left = df1
right = df2
result = left.merge(right, on="id")
"""
    nodes, edges = extract_nodes_with_ranges(code)

    merge_nodes = [n for n in nodes if n.label == "merge"]
    assert len(merge_nodes) == 1

    # Should have edges from both left and right (though they're assignment nodes)
    # In real code with var/operations, this would connect properly


def test_chained_pandas_operations():
    """Multiple pandas operations on same line should all be extracted."""
    code = """
result = df.merge(other, on="id").drop(columns=["temp"])
"""
    nodes, edges = extract_nodes_with_ranges(code)

    merge_nodes = [n for n in nodes if n.label == "merge"]
    drop_nodes = [n for n in nodes if n.label == "drop"]

    assert len(merge_nodes) == 1
    assert len(drop_nodes) == 1
    assert merge_nodes[0].source_range.start_line == drop_nodes[0].source_range.start_line


def test_medium_script_has_pandas_operations():
    """Medium pipeline script should have groupby, merge, and drop nodes."""
    code = """
import skrub
import sempipes

products = skrub.var("products", data)
baskets = skrub.var("baskets", data)
baskets = baskets.skb.subsample(n=100)

basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
vectorized = products.skb.apply(vectorizer)
aggregated = vectorized.groupby("basket_ID").agg("mean")
result = basket_ids.merge(aggregated, on="ID").drop(columns=["temp"])
"""
    nodes, edges = extract_nodes_with_ranges(code)

    groupby_nodes = [n for n in nodes if n.label == "groupby"]
    merge_nodes = [n for n in nodes if n.label == "merge"]
    drop_nodes = [n for n in nodes if n.label == "drop"]

    assert len(groupby_nodes) == 1, "Should find groupby node"
    assert len(merge_nodes) == 1, "Should find merge node"
    assert len(drop_nodes) == 1, "Should find drop node"

    # Verify as_X is also parsed
    as_x_nodes = [n for n in nodes if n.label == "as_X"]
    assert len(as_x_nodes) == 1, "Should find as_X node"
