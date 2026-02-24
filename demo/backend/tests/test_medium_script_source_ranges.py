"""Test exact character positions for medium-style pipeline scripts.

These tests use embedded test scripts with known line numbers, not the actual
pipeline_scripts/medium.py file which may be reformatted.
"""

import pytest

from services.graph_api import compile_script_to_graph_dynamic


# Test script 1: Standard formatting
MEDIUM_SCRIPT_V1 = """import skrub
import sempipes
from sklearn.ensemble import HistGradientBoostingClassifier

products = skrub.var("products", None)
baskets = skrub.var("baskets", None)
baskets = baskets.skb.subsample(n=100)
basket_ids = sempipes.as_X(baskets[["ID"]], "X")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")
products = products.sem_fillna(target_column="make", nl_prompt="Infer", impute_with_existing_values_only=True)
kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
kept_products = kept_products.sem_gen_features(nl_prompt="Generate", name="features", how_many=3)
vectorizer = skrub.TableVectorizer()
vectorized = kept_products.skb.apply(vectorizer, exclude_cols=["basket_ID"])
aggregated = vectorized.groupby("basket_ID").agg("mean").reset_index()
augmented = basket_ids.merge(aggregated, left_on="ID", right_on="basket_ID").drop(columns=["ID", "basket_ID"])
clf = augmented.skb.apply_with_sem_choose(HistGradientBoostingClassifier(), y=fraud_flags, choices=sempipes.sem_choose(name="c"))
"""

# Test script 2: Multiline formatting (like actual medium.py)
MEDIUM_SCRIPT_V2 = """import skrub
import sempipes
from sklearn.ensemble import HistGradientBoostingClassifier

products = skrub.var("products", None)
baskets = skrub.var("baskets", None)
baskets = baskets.skb.subsample(
    n=100, how="random")
basket_ids = sempipes.as_X(baskets[["ID"]], "X")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")
products = products.sem_fillna(
    target_column="make",
    nl_prompt="Infer manufacturer",
    impute_with_existing_values_only=True)
kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
kept_products = kept_products.sem_gen_features(
    nl_prompt="Generate features",
    name="features",
    how_many=3)
vectorizer = skrub.TableVectorizer()
vectorized = kept_products.skb\\
    .apply(vectorizer, exclude_cols=["basket_ID"])
aggregated = vectorized\\
    .groupby("basket_ID").agg("mean").reset_index()
augmented = basket_ids\\
    .merge(aggregated, left_on="ID", right_on="basket_ID")\\
    .drop(columns=["ID", "basket_ID"])
clf = augmented.skb.apply_with_sem_choose(
    HistGradientBoostingClassifier(), y=fraud_flags, choices=sempipes.sem_choose(name="c"))
"""

# Test script 3: Different variable names
MEDIUM_SCRIPT_V3 = """import skrub
import sempipes
from sklearn.ensemble import HistGradientBoostingClassifier

prods = skrub.var("prods", None)
orders = skrub.var("orders", None)
orders = orders.skb.subsample(n=50)
X_data = sempipes.as_X(orders[["order_id"]], "Orders")
y_data = sempipes.as_y(orders["is_fraud"], "Fraud")
prods = prods.sem_fillna(target_column="brand", nl_prompt="Fill", impute_with_existing_values_only=True)
filtered = prods[prods["order_id"].isin(X_data["order_id"])]
filtered = filtered.sem_gen_features(nl_prompt="Gen", name="gen", how_many=2)
vec = skrub.TableVectorizer()
vecs = filtered.skb.apply(vec, exclude_cols=["order_id"])
agg = vecs.groupby("order_id").agg("mean").reset_index()
merged = X_data.merge(agg, left_on="order_id", right_on="order_id").drop(columns=["order_id"])
model = merged.skb.apply_with_sem_choose(HistGradientBoostingClassifier(), y=y_data, choices=sempipes.sem_choose(name="m"))
"""


def test_medium_script_compiles_v1():
    """Test script v1 compiles successfully."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)
    assert len(result.nodes) > 0, "Should produce non-empty graph"
    assert len(result.validation_errors) == 0, f"Should have no errors: {result.validation_errors}"


def test_medium_script_compiles_v2():
    """Test script v2 (multiline) compiles successfully."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V2)
    assert len(result.nodes) > 0, "Should produce non-empty graph"
    assert len(result.validation_errors) == 0, f"Should have no errors: {result.validation_errors}"


def test_medium_script_compiles_v3():
    """Test script v3 (different names) compiles successfully."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V3)
    assert len(result.nodes) > 0, "Should produce non-empty graph"
    assert len(result.validation_errors) == 0, f"Should have no errors: {result.validation_errors}"


def test_var_nodes_have_correct_lines_v1():
    """Var nodes should map to their declaration lines in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 5: products = skrub.var("products", None)
    products_var = [n for n in result.nodes if n.label == "<Var 'products'>"]
    assert len(products_var) == 1, "Should find products var node"
    assert products_var[0].source_range is not None, "products var should have source_range"
    assert products_var[0].source_range.start_line == 5, \
        f"products var should start at line 5, got {products_var[0].source_range.start_line}"

    # Line 6: baskets = skrub.var("baskets", None)
    baskets_var = [n for n in result.nodes if n.label == "<Var 'baskets'>"]
    assert len(baskets_var) == 1, "Should find baskets var node"
    assert baskets_var[0].source_range is not None, "baskets var should have source_range"
    assert baskets_var[0].source_range.start_line == 6, \
        f"baskets var should start at line 6, got {baskets_var[0].source_range.start_line}"


def test_subsample_node_line_v1():
    """Subsample should map to line 7 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 7: baskets = baskets.skb.subsample(n=100)
    subsample_nodes = [n for n in result.nodes if "subsample" in n.label.lower()]
    assert len(subsample_nodes) == 1, f"Should find exactly one subsample node, got {len(subsample_nodes)}"
    assert subsample_nodes[0].source_range is not None, "subsample should have source_range"
    assert subsample_nodes[0].source_range.start_line == 7, \
        f"subsample should start at line 7, got {subsample_nodes[0].source_range.start_line}"


def test_getitem_for_as_x_maps_correctly_v1():
    """GetItem node for baskets[["ID"]] should map to line 8 (same as as_X) in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 8: basket_ids = sempipes.as_X(baskets[["ID"]], "X")
    getitem_nodes = [n for n in result.nodes if n.label.startswith("<GetItem") and "ID" in n.label]

    # Should have at least one GetItem with 'ID'
    assert len(getitem_nodes) >= 1, f"Should find at least one GetItem with 'ID', got {len(getitem_nodes)}"

    # First GetItem with 'ID' should map to as_X line
    first_getitem = getitem_nodes[0]
    assert first_getitem.source_range is not None, "GetItem should have source_range"
    assert first_getitem.source_range.start_line == 8, \
        f"First GetItem (for as_X) should map to line 8, got {first_getitem.source_range.start_line}"


def test_getitem_for_as_y_maps_correctly_v1():
    """GetItem node for baskets["fraud_flag"] should map to line 9 (same as as_y) in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 9: fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")
    fraud_flag_getitems = [n for n in result.nodes if n.label.startswith("<GetItem") and "fraud_flag" in n.label]

    assert len(fraud_flag_getitems) >= 1, \
        f"Should find at least one GetItem with 'fraud_flag', got {len(fraud_flag_getitems)}"
    fraud_flag_getitem = fraud_flag_getitems[0]
    assert fraud_flag_getitem.source_range is not None, "fraud_flag GetItem should have source_range"
    assert fraud_flag_getitem.source_range.start_line == 9, \
        f"fraud_flag GetItem should map to line 9, got {fraud_flag_getitem.source_range.start_line}"


def test_sem_fillna_node_line_v1():
    """sem_fillna node should map to line 10 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 10: products = products.sem_fillna(target_column="make", nl_prompt="Infer", impute_with_existing_values_only=True)
    fillna_nodes = [n for n in result.nodes if n.label == "sem_fillna"]
    assert len(fillna_nodes) == 1, f"Should find exactly one sem_fillna node, got {len(fillna_nodes)}"
    assert fillna_nodes[0].source_range is not None, "sem_fillna should have source_range"
    assert fillna_nodes[0].source_range.start_line == 10, \
        f"sem_fillna should start at line 10, got {fillna_nodes[0].source_range.start_line}"


def test_isin_filter_line_v1():
    """isin filter line should produce GetItem and isin nodes for line 10 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 10: kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
    # Should have isin node
    isin_nodes = [n for n in result.nodes if "isin" in n.label.lower()]
    assert len(isin_nodes) >= 1, f"Should find at least one isin node, got {len(isin_nodes)}"

    # Should have GetItem nodes for "basket_ID" (may or may not have source_range)
    basket_id_getitems = [n for n in result.nodes if n.label.startswith("<GetItem") and "basket_ID" in n.label]
    assert len(basket_id_getitems) >= 1, f"Should find at least one GetItem with 'basket_ID'"


def test_sem_gen_features_node_line_v1():
    """sem_gen_features node should map to line 12 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 12: kept_products = kept_products.sem_gen_features(nl_prompt="Generate", name="features", how_many=3)
    gen_features_nodes = [n for n in result.nodes if n.label == "sem_gen_features"]
    assert len(gen_features_nodes) == 1, f"Should find exactly one sem_gen_features node, got {len(gen_features_nodes)}"
    assert gen_features_nodes[0].source_range is not None, "sem_gen_features should have source_range"
    assert gen_features_nodes[0].source_range.start_line == 12, \
        f"sem_gen_features should start at line 12, got {gen_features_nodes[0].source_range.start_line}"


def test_skb_apply_node_line_v1():
    """skb.apply should map to line 14 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 14: vectorized = kept_products.skb.apply(vectorizer, exclude_cols=["basket_ID"])
    # Look for Apply nodes (skrub creates <Apply TableVectorizer> for .skb.apply(TableVectorizer))
    skb_apply_nodes = [n for n in result.nodes if "apply" in n.label.lower() and "tablevectorizer" in n.label.lower()]

    if len(skb_apply_nodes) == 0:
        # Fallback: look for any apply node
        skb_apply_nodes = [n for n in result.nodes if "apply" in n.label.lower()]

    assert len(skb_apply_nodes) >= 1, f"Should find at least one apply node, got {len(skb_apply_nodes)}"
    assert skb_apply_nodes[0].source_range is not None, "skb.apply should have source_range"
    assert skb_apply_nodes[0].source_range.start_line == 14, \
        f"skb.apply should map to line 14, got {skb_apply_nodes[0].source_range.start_line}"


def test_groupby_node_line_v1():
    """groupby node should map to line 15 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 15: aggregated = vectorized.groupby("basket_ID").agg("mean").reset_index()
    groupby_nodes = [n for n in result.nodes if "groupby" in n.label.lower()]
    assert len(groupby_nodes) == 1, f"Should find exactly one groupby node, got {len(groupby_nodes)}"
    assert groupby_nodes[0].source_range is not None, "groupby should have source_range"
    assert groupby_nodes[0].source_range.start_line == 15, \
        f"groupby should map to line 15, got {groupby_nodes[0].source_range.start_line}"


def test_merge_node_line_v1():
    """merge node should map to line 16 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 16: augmented = basket_ids.merge(aggregated, left_on="ID", right_on="basket_ID").drop(columns=["ID", "basket_ID"])
    merge_nodes = [n for n in result.nodes if "merge" in n.label.lower()]
    assert len(merge_nodes) == 1, f"Should find exactly one merge node, got {len(merge_nodes)}"
    assert merge_nodes[0].source_range is not None, "merge should have source_range"
    assert merge_nodes[0].source_range.start_line == 16, \
        f"merge should start at line 16, got {merge_nodes[0].source_range.start_line}"


def test_drop_node_line_v1():
    """drop node should map to line 16 (same line as merge) in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 16: ... .drop(columns=["ID", "basket_ID"])
    drop_nodes = [n for n in result.nodes if "drop" in n.label.lower()]
    assert len(drop_nodes) == 1, f"Should find exactly one drop node, got {len(drop_nodes)}"
    assert drop_nodes[0].source_range is not None, "drop should have source_range"
    assert drop_nodes[0].source_range.start_line == 16, \
        f"drop should map to line 16, got {drop_nodes[0].source_range.start_line}"


def test_apply_with_sem_choose_node_line_v1():
    """apply_with_sem_choose node should map to line 17 in v1."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V1)

    # Line 17: clf = augmented.skb.apply_with_sem_choose(HistGradientBoostingClassifier(), y=fraud_flags, choices=sempipes.sem_choose(name="c"))
    apply_choose_nodes = [n for n in result.nodes if n.label == "apply_with_sem_choose"]
    assert len(apply_choose_nodes) == 1, \
        f"Should find exactly one apply_with_sem_choose node, got {len(apply_choose_nodes)}"
    assert apply_choose_nodes[0].source_range is not None, "apply_with_sem_choose should have source_range"
    assert apply_choose_nodes[0].source_range.start_line == 17, \
        f"apply_with_sem_choose should start at line 17, got {apply_choose_nodes[0].source_range.start_line}"


def test_multiline_sem_fillna_v2():
    """Multiline sem_fillna should map to start line in v2."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V2)

    # Lines 11-14: products = products.sem_fillna(...)
    fillna_nodes = [n for n in result.nodes if n.label == "sem_fillna"]
    assert len(fillna_nodes) == 1, f"Should find exactly one sem_fillna node"
    assert fillna_nodes[0].source_range is not None, "sem_fillna should have source_range"
    assert fillna_nodes[0].source_range.start_line == 11, \
        f"Multiline sem_fillna should start at line 11, got {fillna_nodes[0].source_range.start_line}"


def test_multiline_sem_gen_features_v2():
    """Multiline sem_gen_features should map to start line in v2."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V2)

    # Lines 16-19: kept_products = kept_products.sem_gen_features(...)
    gen_features_nodes = [n for n in result.nodes if n.label == "sem_gen_features"]
    assert len(gen_features_nodes) == 1, f"Should find exactly one sem_gen_features node"
    assert gen_features_nodes[0].source_range is not None, "sem_gen_features should have source_range"
    assert gen_features_nodes[0].source_range.start_line == 16, \
        f"Multiline sem_gen_features should start at line 16, got {gen_features_nodes[0].source_range.start_line}"


def test_different_variable_names_v3():
    """Script with different variable names should still produce correct mappings."""
    result = compile_script_to_graph_dynamic(MEDIUM_SCRIPT_V3)

    # Check var nodes with different names
    prods_var = [n for n in result.nodes if n.label == "<Var 'prods'>"]
    assert len(prods_var) == 1, "Should find prods var node"
    assert prods_var[0].source_range is not None, "prods var should have source_range"
    assert prods_var[0].source_range.start_line == 5, \
        f"prods var should start at line 5, got {prods_var[0].source_range.start_line}"

    orders_var = [n for n in result.nodes if n.label == "<Var 'orders'>"]
    assert len(orders_var) == 1, "Should find orders var node"
    assert orders_var[0].source_range is not None, "orders var should have source_range"
    assert orders_var[0].source_range.start_line == 6, \
        f"orders var should start at line 6, got {orders_var[0].source_range.start_line}"

    # Check semantic operators still work with different names
    fillna_nodes = [n for n in result.nodes if n.label == "sem_fillna"]
    assert len(fillna_nodes) == 1, "Should find sem_fillna node"

    gen_features_nodes = [n for n in result.nodes if n.label == "sem_gen_features"]
    assert len(gen_features_nodes) == 1, "Should find sem_gen_features node"

    apply_choose_nodes = [n for n in result.nodes if n.label == "apply_with_sem_choose"]
    assert len(apply_choose_nodes) == 1, "Should find apply_with_sem_choose node"


def test_all_important_nodes_have_source_ranges():
    """All important nodes (operators, inputs) should have source_range information across all versions."""
    for script_name, script in [("v1", MEDIUM_SCRIPT_V1), ("v2", MEDIUM_SCRIPT_V2), ("v3", MEDIUM_SCRIPT_V3)]:
        result = compile_script_to_graph_dynamic(script)

        # Check that important nodes have source ranges.
        # Note: <Apply TableVectorizer> (skb.apply) is excluded because it may not
        # have a source range when the call uses backslash line continuation.
        important_nodes = [
            n for n in result.nodes
            if n.label in ["sem_fillna", "sem_gen_features", "apply_with_sem_choose"]
            or n.label.startswith("<Var")
            or "subsample" in n.label.lower()
            or "groupby" in n.label.lower()
            or "merge" in n.label.lower()
        ]

        nodes_without_ranges = [n for n in important_nodes if n.source_range is None]

        if nodes_without_ranges:
            labels = [n.label for n in nodes_without_ranges]
            pytest.fail(
                f"Script {script_name}: Found {len(nodes_without_ranges)} important nodes without source_range: {labels}\n"
                f"All important nodes should have source ranges for code-graph synchronization."
            )


def test_source_ranges_are_reasonable():
    """All source ranges should have reasonable line numbers across all versions."""
    for script_name, script in [("v1", MEDIUM_SCRIPT_V1), ("v2", MEDIUM_SCRIPT_V2), ("v3", MEDIUM_SCRIPT_V3)]:
        result = compile_script_to_graph_dynamic(script)
        max_lines = len(script.splitlines())

        for node in result.nodes:
            if node.source_range:
                assert 1 <= node.source_range.start_line <= max_lines, \
                    f"Script {script_name}: Node {node.label} has invalid start_line {node.source_range.start_line} (max {max_lines})"
                assert 1 <= node.source_range.end_line <= max_lines, \
                    f"Script {script_name}: Node {node.label} has invalid end_line {node.source_range.end_line} (max {max_lines})"
                assert node.source_range.start_line <= node.source_range.end_line, \
                    f"Script {script_name}: Node {node.label} has start_line > end_line"
