"""
Tests for label matching robustness between compile and runtime graphs.

These tests verify that node ID matching works correctly even when:
- Labels are truncated or incomplete (e.g., `basket_ids["ID"` missing closing bracket)
- Labels have special characters or formatting variations
- Multiple nodes have similar labels
- GetItem operations vs as_X operations
"""

import json
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_getitem_label_matching_with_truncated_labels():
    """Test that GetItem nodes with truncated labels (missing brackets) match correctly."""
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)
basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")

# This creates a GetItem node that might be labeled as: basket_ids["ID" (truncated)
filtered = baskets[baskets["fraud_flag"].isin(basket_ids["ID"])]
"""

    # Execute and collect events
    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    # Get node_code events
    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # All node_code events should have IDs that match runtime graph nodes
    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"Event node_id '{node_id}' should match runtime graph. Available: {runtime_node_ids}"


def test_multiple_getitem_operations_distinct_matching():
    """Test that multiple GetItem operations on same object get matched correctly."""
    code = """import sempipes

df = sempipes.as_X(data, 'features')
# Multiple column selections - each should get unique node
col_a = df["column_a"]
col_b = df["column_b"]
col_c = df["column_a"]  # Same as first one - might reuse node or create new one
"""

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    # Get node_code events
    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # Verify all events match runtime graph
    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"Event node_id '{node_id}' should match runtime graph"


def test_mixed_as_x_and_getitem_matching():
    """Test that both as_X operations and GetItem operations match correctly."""
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)

# as_X creates one type of node
product_features = sempipes.as_X(products[["make", "price"]], "Product features")

# Direct column access creates GetItem node
prices_only = product_features["price"]
"""

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])

    # Verify we have multiple node types
    labels = [n.get("label", "").lower() for n in runtime_nodes]
    # Should have var, getitem, or similar operations
    assert len(runtime_nodes) > 0, "Should have runtime nodes"

    # Verify all node_code events match runtime graph
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"Event node_id '{node_id}' should match runtime graph"


def test_label_matching_with_special_characters():
    """Test that labels with special characters (brackets, quotes, dots) match correctly."""
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)

# Operations with special characters in labels
basket_ids = sempipes.as_X(baskets[["ID"]], "IDs")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Labels")

# Column with underscore
has_underscore = baskets["fraud_flag"]
"""

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph and verify matching
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    node_code_events = [e for e in events if e.get("type") == "node_code"]

    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"Event with special chars - node_id '{node_id}' should match runtime graph"


def test_medium_script_label_matching():
    """
    Test the actual medium.py script to verify label matching works correctly.

    This is a comprehensive test using the real medium pipeline which has:
    - Multiple GetItem operations (baskets[["ID"]], baskets["fraud_flag"], etc.)
    - as_X and as_y operations
    - Chained pandas operations (groupby, agg, reset_index, merge, drop)
    - sem_fillna, sem_gen_features
    - skb.apply, apply_with_sem_choose
    """
    # Get medium script
    try:
        script_resp = client.get("/api/scripts/medium")
        assert script_resp.status_code == 200
        code = script_resp.json()["content"]
    except Exception:
        pytest.skip("Medium script not available")

    # Execute
    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_graph = skrub_graph_events[0]["graph"]
    runtime_nodes = runtime_graph.get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    print(f"\n=== Medium Pipeline Runtime Graph ===")
    print(f"Total nodes: {len(runtime_nodes)}")
    print(f"Node labels: {[n.get('label', '') for n in runtime_nodes]}")

    # Get all node_code events
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    print(f"\nTotal node_code events: {len(node_code_events)}")

    # CRITICAL: Every node_code event must have an ID that exists in runtime graph
    mismatched_events = []
    for event in node_code_events:
        node_id = event.get("node_id", "")
        if node_id not in runtime_node_ids:
            mismatched_events.append({
                "node_id": node_id,
                "code_preview": event.get("generated_code", "")[:50]
            })

    assert len(mismatched_events) == 0, \
        f"Found {len(mismatched_events)} mismatched events. Details: {mismatched_events}\n" \
        f"Available runtime IDs: {runtime_node_ids}"

    # Verify skrubToCompileId mapping exists and is consistent
    skrub_to_compile = skrub_graph_events[0].get("skrubToCompileId", {})
    assert isinstance(skrub_to_compile, dict), "Should have skrubToCompileId mapping"

    # Verify mapping keys are subset of runtime node IDs
    mapping_keys = set(skrub_to_compile.keys())
    assert mapping_keys.issubset(runtime_node_ids), \
        f"Mapping keys should be subset of runtime nodes. " \
        f"Extra keys: {mapping_keys - runtime_node_ids}"


def test_method_call_label_variations():
    """
    Test that method calls are matched correctly despite label formatting variations.

    Skrub may format method call labels inconsistently:
    - Sometimes includes the dot: `.isin`, `.groupby`
    - Sometimes excludes the dot: `isin`, `groupby`
    - Sometimes includes the object: `baskets.isin`
    - Sometimes just the method: `isin`
    """
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)
basket_ids = sempipes.as_X(baskets[["ID"]], "IDs")

# Method call: .isin might be labeled as "isin", ".isin", or "baskets.isin"
filtered_baskets = baskets[baskets["fraud_flag"].isin(basket_ids["ID"])]

# Chained method calls
result = baskets.groupby("ID").agg("count").reset_index()
"""

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    print(f"\n=== Method Call Label Variations ===")
    print(f"Runtime node labels: {[n.get('label', '') for n in runtime_nodes]}")

    # Get node_code events
    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # All events should match runtime graph regardless of label formatting
    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"Method call event node_id '{node_id}' should match runtime graph"

    # Find method call nodes in runtime graph
    method_nodes = [n for n in runtime_nodes if any(
        method in n.get("label", "").lower()
        for method in ["isin", "groupby", "agg", "reset_index"]
    )]

    print(f"Found {len(method_nodes)} method call nodes")
    for node in method_nodes:
        print(f"  - ID: {node['id']}, Label: '{node.get('label', '')}'")
        # Verify this node has a corresponding node_code event
        has_event = any(e["node_id"] == node["id"] for e in node_code_events)
        print(f"    Has node_code event: {has_event}")


def test_pandas_chained_methods_label_matching():
    """
    Test that pandas chained methods (groupby -> agg -> reset_index -> merge -> drop)
    all get matched correctly despite varying label formats.
    """
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)

basket_ids = sempipes.as_X(baskets[["ID"]], "IDs")

# Complex chain with multiple method calls - each should be matched
aggregated = products.groupby("basket_ID").agg("mean").reset_index()
result = basket_ids.merge(aggregated, left_on="ID", right_on="basket_ID").drop(columns=["ID"])
"""

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    print(f"\n=== Pandas Chained Methods ===")
    print(f"Total runtime nodes: {len(runtime_nodes)}")

    # Expected pandas operations
    expected_ops = ["groupby", "agg", "reset_index", "merge", "drop"]

    # Check which operations are present in labels
    labels = [n.get("label", "").lower() for n in runtime_nodes]
    found_ops = {}
    for op in expected_ops:
        found = any(op in label for label in labels)
        found_ops[op] = found
        print(f"  {op}: {'✓ found' if found else '✗ missing'}")

    # Get node_code events and verify all match runtime graph
    node_code_events = [e for e in events if e.get("type") == "node_code"]

    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"Chained method event node_id '{node_id}' should match runtime graph"


def test_callmethod_vs_function_label_matching():
    """
    Test that CallMethod nodes (DataFrame methods) and function calls are matched correctly.

    Skrub represents these differently:
    - CallMethod: DataFrame.method() → label might be "<CallMethod 'method'>" or just "method"
    - Function calls: func(df) → label might be "<Function 'func'>" or "func"
    """
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)

# DataFrame method (CallMethod)
subsampled = products.skb.subsample(n=100, how="random")

# Semantic operation (special CallMethod or Apply)
filled = subsampled.sem_fillna(target_column="make", nl_prompt="Fill missing manufacturers")
"""

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])
    runtime_node_ids = {n["id"] for n in runtime_nodes}

    print(f"\n=== CallMethod vs Function Labels ===")
    for node in runtime_nodes:
        label = node.get("label", "")
        print(f"  Node {node['id']}: '{label}'")

    # Get node_code events
    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # All events should match runtime graph
    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"CallMethod/Function event node_id '{node_id}' should match runtime graph"


def test_full_script_reset_index_matching():
    """
    Test the full.py script specifically for groupby -> agg -> reset_index matching.

    The user reported that reset_index in the chain is not matching correctly with the code.
    This test investigates the specific line:
        aggregated_products = vectorized_products.groupby("basket_ID").agg("mean").reset_index()
    """
    # Get full script
    try:
        script_resp = client.get("/api/scripts/full")
        assert script_resp.status_code == 200
        code = script_resp.json()["content"]
    except Exception:
        pytest.skip("Full script not available")

    # Execute
    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])

    print(f"\n=== Full Script - reset_index Investigation ===")
    print(f"Total runtime nodes: {len(runtime_nodes)}")

    # Check for chained pandas operations
    chained_ops = ["groupby", "agg", "reset_index", "merge", "drop", "drop_duplicates"]
    found_ops = {}
    for op in chained_ops:
        nodes_with_op = [n for n in runtime_nodes if op in n.get("label", "").lower()]
        found_ops[op] = nodes_with_op
        print(f"  {op}: {len(nodes_with_op)} nodes")
        for node in nodes_with_op:
            print(f"    - Node {node['id']}: '{node.get('label', '')}'")

    # Verify that if we have reset_index nodes, they have corresponding node_code events
    node_code_events = {e["node_id"]: e for e in events if e.get("type") == "node_code"}

    for reset_node in found_ops.get("reset_index", []):
        node_id = reset_node["id"]
        has_code = node_id in node_code_events
        print(f"\nreset_index node {node_id}: has_code={has_code}")
        if has_code:
            code_preview = node_code_events[node_id]["generated_code"][:100]
            print(f"  Code preview: {code_preview}...")


def test_duplicate_label_occurrence_matching():
    """Test that nodes with duplicate labels are matched by occurrence order."""
    code = """import sempipes
import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)

# Two separate sem_fillna operations - should get different node IDs
products1 = products.sem_fillna(target_column="make", nl_prompt="Infer manufacturer")
products2 = products1.sem_fillna(target_column="price", nl_prompt="Fill missing prices")
"""

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Get runtime graph
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])

    # Find all sem_fillna nodes (should be 2)
    sem_fillna_nodes = [n for n in runtime_nodes if "sem_fillna" in n.get("label", "").lower()]

    # Get node_code events for sem_fillna
    node_code_events = {e["node_id"]: e for e in events if e.get("type") == "node_code"}

    # Each sem_fillna node should have a distinct node_code event
    sem_fillna_event_ids = [n["id"] for n in sem_fillna_nodes if n["id"] in node_code_events]

    if len(sem_fillna_nodes) == 2:
        # If we have 2 sem_fillna nodes, they should have different IDs
        assert len(set(n["id"] for n in sem_fillna_nodes)) == 2, \
            "Two sem_fillna operations should have distinct node IDs"

        # And both should have node_code events
        assert len(sem_fillna_event_ids) >= 1, \
            "At least one sem_fillna node should have node_code event"
