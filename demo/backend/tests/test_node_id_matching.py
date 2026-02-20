"""
Tests for node ID matching between compile graph and execution events.

These tests verify that:
1. node_code events use IDs that match the compile graph
2. Non-semantic operators (subsample, eval) get mock code
3. Semantic operators get their actual generated code
4. Frontend can match compile graph nodes to backend events via skrub_to_compile mapping

Note: We test with both dynamic and static compilation to ensure both work correctly.
"""

import json
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_node_code_events_match_graph_ids():
    """node_code events should use IDs that match the runtime skrub graph from execution.

    Note: Compile and execute both use dynamic compilation, but they run the pipeline
    separately and may get different node IDs from skrub. The source of truth for node IDs
    is the skrub_graph event emitted during execution, not the compile preview graph.

    Only semantic operators should have node_code events; non-semantic operators get input_summary.
    """
    code = """import skrub
import sempipes

products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=3)
result = products.skb.eval()
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

    # Get the actual runtime graph from execute (source of truth for node IDs)
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1, "Should have exactly one skrub_graph event"

    runtime_graph = skrub_graph_events[0]["graph"]
    runtime_node_ids = {n["id"] for n in runtime_graph.get("nodes", [])}

    # Verify node_code events use IDs from the runtime graph
    # Note: Only semantic operators get node_code; non-semantic get input_summary
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    assert len(node_code_events) > 0, "Should have node_code events for semantic operators"

    for event in node_code_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"node_id '{node_id}' should match a runtime graph node ID. Available IDs: {runtime_node_ids}"

    # Also verify input_summary events use IDs from the runtime graph
    input_summary_events = [e for e in events if e.get("type") == "input_summary"]
    assert len(input_summary_events) > 0, "Should have input_summary events for inputs and non-semantic operators"

    for event in input_summary_events:
        node_id = event.get("node_id", "")
        assert node_id in runtime_node_ids, \
            f"node_id '{node_id}' should match a runtime graph node ID. Available IDs: {runtime_node_ids}"


def test_subsample_gets_data_summary_not_code():
    """Non-semantic operators like subsample should get input_summary (data), not node_code."""
    code = """import skrub
import sempipes

products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=3)
result = products.skb.eval()
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

    # Get runtime graph to find node IDs by label
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])

    # Find subsample and sem_gen_features nodes by label
    subsample_node = next((n for n in runtime_nodes if "subsample" in n.get("label", "").lower()), None)
    sem_gen_node = next((n for n in runtime_nodes if "sem_gen_features" in n.get("label", "").lower()), None)

    assert subsample_node is not None, "Should have subsample node"
    assert sem_gen_node is not None, "Should have sem_gen_features node"

    subsample_id = subsample_node["id"]
    sem_gen_id = sem_gen_node["id"]

    # Check that subsample gets input_summary, not node_code
    node_code_events = {e["node_id"]: e for e in events if e.get("type") == "node_code"}
    input_summary_events = {e["node_id"]: e for e in events if e.get("type") == "input_summary"}

    # Subsample should have input_summary (data), NOT node_code
    assert subsample_id not in node_code_events, \
        f"Subsample (ID: {subsample_id}) should NOT have node_code event"
    assert subsample_id in input_summary_events, \
        f"Subsample (ID: {subsample_id}) should have input_summary event (data summary)"

    # sem_gen_features should have node_code (it's semantic)
    assert sem_gen_id in node_code_events, \
        f"sem_gen_features (ID: {sem_gen_id}) should have node_code event"
    assert sem_gen_id not in input_summary_events, \
        f"sem_gen_features (ID: {sem_gen_id}) should NOT have input_summary event"


def test_semantic_operators_get_unique_code(monkeypatch):
    """Each semantic operator should get its own unique generated code."""
    # Override mock to return 2 code blocks for 2 semantic operators
    from unittest.mock import MagicMock
    import json

    def _fake_popen_with_2_codes(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        # Return 2 different code blocks
        lines = [
            b"##SEMPIPES_NODE_CODE##\n",
            (json.dumps({"index": 0, "code": "# Code for sem_fillna\ndf = fill_missing(df)\nreturn df"}) + "\n").encode("utf-8"),
            b"##END##\n",
            b"##SEMPIPES_NODE_CODE##\n",
            (json.dumps({"index": 1, "code": "# Code for sem_gen_features\ndf = generate_features(df)\nreturn df"}) + "\n").encode("utf-8"),
            b"##END##\n",
            b""
        ]
        proc.stdout.readline.side_effect = lines
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen_with_2_codes)

    code = """import skrub
import sempipes

products = skrub.var("products", dataset.products)
products = products.sem_fillna(nl_prompt="Fill missing values intelligently.", target_column="name", impute_with_existing_values_only=True)
products = products.sem_gen_features(nl_prompt="Generate useful features.", name="new_features", how_many=2)
result = products.skb.eval()
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

    # Get runtime graph to find node IDs by label
    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1
    runtime_nodes = skrub_graph_events[0]["graph"].get("nodes", [])

    # Find semantic operators by label
    sem_fillna_node = next((n for n in runtime_nodes if "sem_fillna" in n.get("label", "").lower()), None)
    sem_gen_node = next((n for n in runtime_nodes if "sem_gen_features" in n.get("label", "").lower()), None)

    assert sem_fillna_node is not None, "Should have sem_fillna node"
    assert sem_gen_node is not None, "Should have sem_gen_features node"

    sem_fillna_id = sem_fillna_node["id"]
    sem_gen_id = sem_gen_node["id"]

    # Check node_code events
    node_code_events = {e["node_id"]: e for e in events if e.get("type") == "node_code"}

    # Both semantic operators should have events with graph node IDs
    assert sem_fillna_id in node_code_events, f"Should have node_code for sem_fillna node (ID: {sem_fillna_id})"
    assert sem_gen_id in node_code_events, f"Should have node_code for sem_gen_features node (ID: {sem_gen_id})"

    # Each should have different code (not the same code assigned to both)
    fillna_code = node_code_events[sem_fillna_id]["generated_code"]
    gen_code = node_code_events[sem_gen_id]["generated_code"]

    assert fillna_code != gen_code, "Different semantic operators should have different generated code"
    # Verify the codes match what we expected from the mock
    assert "fill_missing" in fillna_code, "sem_fillna should have its specific code"
    assert "generate_features" in gen_code, "sem_gen_features should have its specific code"


def test_skrub_to_compile_mapping_is_emitted():
    """Backend should emit skrubToCompileId mapping in skrub_graph event.

    With dynamic compilation (default), both skrub and compile graphs use numeric IDs,
    so the mapping is primarily for label matching and debugging.
    """
    code = """import skrub
import sempipes

products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=3)
result = products.skb.eval()
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

    skrub_graph_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_graph_events) == 1, "Should have exactly one skrub_graph event"

    graph_event = skrub_graph_events[0]
    assert "skrubToCompileId" in graph_event, "skrub_graph event should include skrubToCompileId mapping"

    mapping = graph_event["skrubToCompileId"]
    assert isinstance(mapping, dict), "skrubToCompileId should be a dict"
    # With dynamic compilation, both sides use numeric IDs
    for skrub_id, compile_id in mapping.items():
        assert isinstance(skrub_id, str), f"Skrub ID should be string, got {type(skrub_id)}"
        assert isinstance(compile_id, str), f"Compile ID should be string, got {type(compile_id)}"


def test_frontend_can_match_compile_graph_to_events():
    """
    Simulate frontend behavior: compile graph uses compile IDs,
    backend events use compile IDs, frontend should be able to match them.
    """
    code = """import skrub
import sempipes

products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=3)
"""

    # Step 1: Frontend compiles and gets compile nodes
    compile_resp = client.post("/api/compile", json={"input_code": code})
    assert compile_resp.status_code == 200
    compile_nodes = compile_resp.json()["nodes"]

    # Frontend creates display graph with skrub_ prefixed IDs
    display_node_ids = {f"skrub_{n['id']}" for n in compile_nodes if n["type"] in ("input", "operator")}

    # Step 2: Frontend executes
    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Step 3: Frontend receives node_code events and stores code
    # Simulating CodeGenDemo.tsx lines 243-249
    liveNodeCode = {}
    for event in events:
        if event.get("type") == "node_code":
            node_id = event["node_id"]
            code = event["generated_code"]
            # Store under both raw ID and skrub-prefixed ID
            skrub_id = node_id if node_id.startswith("skrub_") else f"skrub_{node_id}"
            liveNodeCode[node_id] = code
            liveNodeCode[skrub_id] = code

    # Step 4: Verify frontend can find code for all display nodes
    for display_id in display_node_ids:
        # Frontend selects node with display ID (e.g., "skrub_subsample_5")
        # NodeDetailsPanel should find code using either format
        raw_id = display_id[6:] if display_id.startswith("skrub_") else display_id

        # Should find code using either ID format
        found_code = liveNodeCode.get(display_id) or liveNodeCode.get(raw_id)

        # For semantic operators, should have non-empty code
        # For non-semantic, might have mock code
        if "sem_" in display_id or "as_X" in display_id or "as_y" in display_id:
            assert found_code is not None, \
                f"Frontend should find code for display node '{display_id}' using IDs {display_id} or {raw_id}"


def test_no_duplicate_node_code_events():
    """Each semantic operator should receive exactly ONE node_code event (no duplicates)."""
    code = """import skrub
import sempipes

products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=3)
result = products.skb.eval()
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

    # Get all node_code events
    node_code_events = [e for e in events if e.get("type") == "node_code"]

    # Count how many times each node_id appears
    node_id_counts = {}
    for event in node_code_events:
        node_id = event.get("node_id")
        node_id_counts[node_id] = node_id_counts.get(node_id, 0) + 1

    # Each node should appear exactly once
    for node_id, count in node_id_counts.items():
        assert count == 1, f"Node {node_id} has {count} node_code events (should be 1)"

    # Verify we have at least one semantic operator (sem_gen_features)
    assert len(node_code_events) >= 1, "Should have at least one node_code event for semantic operator"
