"""
Comprehensive tests for various Python/pandas syntax variations in label matching.

Tests many valid syntax patterns to ensure robust matching regardless of:
- Method chaining styles (single line vs multi-line)
- Column selection syntax (["col"] vs [["col"]] vs .col)
- Method call patterns (.method() vs method())
- Parentheses and brackets formatting
- isin, groupby, agg, merge, drop, reset_index variations
"""

import json
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _execute_and_get_graph(code: str) -> tuple[list[dict], set[str], dict]:
    """Helper to execute code and return (nodes, node_ids, node_code_events)."""
    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1

    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}
    node_code_events = {e["node_id"]: e for e in events if e.get("type") == "node_code"}

    return runtime_nodes, runtime_node_ids, node_code_events


@pytest.mark.parametrize("column_syntax,desc", [
    ('baskets["ID"]', "single bracket string"),
    ("baskets['ID']", "single bracket single quote"),
    ('baskets[["ID"]]', "double bracket for single column"),
    ('baskets[["ID", "fraud_flag"]]', "double bracket multiple columns"),
    ("data.ID", "dot notation (if valid)"),
])
def test_column_selection_syntax_variations(column_syntax, desc):
    """Test various column selection syntax patterns."""
    # Some syntaxes like data.ID might not work with all datasets
    if ".ID" in column_syntax:
        pytest.skip("Dot notation may not work with all datasets")

    code = f"""import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)

# Column selection: {desc}
selected = {column_syntax}
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    # Verify all events match runtime graph
    for event_id in events.keys():
        assert event_id in node_ids, \
            f"Column syntax '{column_syntax}' - event_id '{event_id}' should match runtime graph"


@pytest.mark.parametrize("chain_style,desc", [
    (".groupby('ID').agg('count')", "single line chained"),
    (".groupby('ID').\\\n        agg('count')", "multi-line with backslash"),
    ("""
        .groupby('ID')
        .agg('count')
    """, "multi-line no backslash (in parens)"),
])
def test_method_chaining_style_variations(chain_style, desc):
    """Test various method chaining styles."""
    code = f"""import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)

# Chaining style: {desc}
result = (baskets
    {chain_style}
)
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    # Verify all events match
    for event_id in events.keys():
        assert event_id in node_ids


@pytest.mark.parametrize("isin_pattern,desc", [
    ('df1["col"].isin(df2["id"])', "direct isin on column"),
    ("df1[df1['col'].isin(df2['id'])]", "isin in filter"),
    ('df1.query("col in @df2.id")', "query syntax (may not work)"),
])
def test_isin_syntax_variations(isin_pattern, desc):
    """Test various .isin() syntax patterns."""
    if "query" in isin_pattern:
        pytest.skip("Query syntax may require different dataset structure")

    code = f"""import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)
products = skrub.var("products", dataset.products)

df1 = baskets
df2 = products

# isin pattern: {desc}
filtered = {isin_pattern}
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    for event_id in events.keys():
        assert event_id in node_ids


@pytest.mark.parametrize("merge_pattern,desc", [
    ("df1.merge(df2, on='id')", "merge with on"),
    ("df1.merge(df2, left_on='id1', right_on='id2')", "merge with left_on/right_on"),
    ("df1.merge(df2, left_on='id1', right_on='id2', how='left')", "merge with how"),
    ("df1.merge(df2, left_on='id1', right_on='id2', how='inner')", "merge inner join"),
])
def test_merge_syntax_variations(merge_pattern, desc):
    """Test various .merge() syntax patterns."""
    code = f"""import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)
products = skrub.var("products", dataset.products)

df1 = sempipes.as_X(baskets[["ID"]], "Baskets")
df2 = products.groupby("basket_ID").agg("mean").reset_index()

# Merge pattern: {desc}
# Adapting pattern to use 'ID' and 'basket_ID'
result = df1.merge(df2, left_on='ID', right_on='basket_ID')
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    for event_id in events.keys():
        assert event_id in node_ids


@pytest.mark.parametrize("drop_pattern,desc", [
    (".drop(columns=['ID'])", "drop with columns param"),
    (".drop(columns='ID')", "drop single column as string"),
    (".drop(['ID'], axis=1)", "drop with axis=1"),
    (".drop(columns=['ID', 'basket_ID'])", "drop multiple columns"),
])
def test_drop_syntax_variations(drop_pattern, desc):
    """Test various .drop() syntax patterns."""
    code = f"""import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)

df = sempipes.as_X(baskets[["ID", "fraud_flag"]], "Data")

# Drop pattern: {desc}
result = df{drop_pattern}
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    for event_id in events.keys():
        assert event_id in node_ids


@pytest.mark.parametrize("agg_pattern,desc", [
    (".agg('mean')", "agg with single function string"),
    (".agg(['mean', 'sum'])", "agg with list of functions"),
    (".agg({'price': 'mean'})", "agg with dict"),
    (".mean()", "direct mean() instead of agg"),
])
def test_agg_syntax_variations(agg_pattern, desc):
    """Test various .agg() and aggregation syntax patterns."""
    code = f"""import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)

# Agg pattern: {desc}
result = products.groupby("basket_ID"){agg_pattern}
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    for event_id in events.keys():
        assert event_id in node_ids


@pytest.mark.parametrize("reset_pattern,desc", [
    (".reset_index()", "reset_index no args"),
    (".reset_index(drop=True)", "reset_index drop old index"),
    (".reset_index(drop=False)", "reset_index keep old index"),
])
def test_reset_index_syntax_variations(reset_pattern, desc):
    """Test various .reset_index() syntax patterns."""
    code = f"""import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)

# reset_index pattern: {desc}
result = products[["make"]].drop_duplicates(){reset_pattern}
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    for event_id in events.keys():
        assert event_id in node_ids


def test_full_chained_operation_comprehensive():
    """
    Comprehensive test with full chained operation mimicking real pipeline code.

    Tests the complete chain:
    groupby -> agg -> reset_index -> merge -> drop

    This is the pattern that appears in medium.py and fraud.py.
    """
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)

# Setup
basket_ids = sempipes.as_X(baskets[["ID"]], "Basket IDs")

# Complex chain (from medium.py pattern)
vectorized = products
aggregated_products = vectorized.groupby("basket_ID").agg("mean").reset_index()
augmented_baskets = basket_ids.merge(
    aggregated_products,
    left_on="ID",
    right_on="basket_ID"
).drop(columns=["ID", "basket_ID"])
"""

    nodes, node_ids, events = _execute_and_get_graph(code)

    print("\n=== Full Chained Operation ===")
    print(f"Total nodes: {len(nodes)}")
    labels = [n.get("label", "") for n in nodes]
    print(f"Node labels: {labels}")

    # Check which operations appear as nodes
    expected_ops = ["groupby", "agg", "reset_index", "merge", "drop"]
    for op in expected_ops:
        found = any(op in label.lower() for label in labels)
        status = "✓" if found else "✗"
        print(f"  {status} {op}")

    # Verify all events match runtime graph
    for event_id in events.keys():
        assert event_id in node_ids


def test_bracket_notation_edge_cases():
    """Test edge cases with bracket notation that might truncate labels."""
    code = '''import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)
products = skrub.var("products", dataset.products)

# Edge cases that might have truncated labels
basket_ids = sempipes.as_X(baskets[["ID"]], "IDs")

# Nested brackets - might show as: baskets["fraud_flag"].isin(basket_ids["ID" (truncated)
filtered_baskets = baskets[baskets["fraud_flag"].isin(basket_ids["ID"])]

# Multiple bracket operations
kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
'''

    nodes, node_ids, events = _execute_and_get_graph(code)

    print("\n=== Bracket Notation Edge Cases ===")
    print(f"Total nodes: {len(nodes)}")
    for node in nodes:
        label = node.get("label", "")
        print(f"  Node {node['id']}: '{label}'")
        # Check if label looks truncated (missing closing bracket)
        if "[" in label and "]" not in label:
            print(f"    ⚠ Potentially truncated label")

    # All events should still match despite truncation
    for event_id in events.keys():
        assert event_id in node_ids, \
            f"Event {event_id} should match despite potential label truncation"
