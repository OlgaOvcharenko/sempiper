"""
Demo backend tests.

We keep tests close to sempipes but NEVER call real LLMs. We simulate correct
behaviour via mocks:

- conftest.py: patches litellm.completion / batch_completion when available.
- Execute tests: the demo gets operator code from the pipeline run (subprocess
  skrub_graph_runner prints ##SEMPIPES_NODE_CODE##). conftest mocks Popen to
  return stdout with those blocks so tests never run the real runner or LLM.
- test_sempipes_code_generation_uses_mock_no_llm_call: patches
  sempipes.llm.llm._generate_code_from_messages so direct sempipes code-gen
  returns fixed code without hitting the network.
"""

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- Pipeline scripts (GET /api/scripts, GET /api/scripts/{name}) ---


def test_list_scripts_returns_200_and_manifest():
    """GET /api/scripts returns list of script entries (id, label) from manifest."""
    resp = client.get("/api/scripts")
    assert resp.status_code == 200
    data = resp.json()
    assert "scripts" in data
    scripts = data["scripts"]
    assert isinstance(scripts, list)
    ids = {s["id"] for s in scripts}
    assert "simple" in ids
    assert "medium" in ids
    assert "full" in ids
    for s in scripts:
        assert "id" in s and "label" in s
        assert isinstance(s["id"], str)
        assert isinstance(s["label"], str)


def test_get_script_content_simple_returns_200_and_content():
    """GET /api/scripts/simple returns id, label, and file content."""
    resp = client.get("/api/scripts/simple")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "simple"
    assert "label" in data
    assert "content" in data
    assert isinstance(data["content"], str)
    assert len(data["content"]) > 0
    assert "as_X" in data["content"]
    assert "sempipes" in data["content"]


def test_get_script_content_medium_and_full_return_200():
    """GET /api/scripts/medium and full return 200 and non-empty content."""
    for name in ("medium", "full"):
        resp = client.get(f"/api/scripts/{name}")
        assert resp.status_code == 200, f"GET /api/scripts/{name} should return 200"
        data = resp.json()
        assert data["id"] == name
        assert "content" in data
        assert len(data["content"]) > 0


def test_get_script_content_unknown_returns_404():
    """GET /api/scripts/{unknown} returns 404 when script id is not in manifest."""
    resp = client.get("/api/scripts/nonexistent-script-id")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert "nonexistent" in data["detail"].lower() or "not found" in data["detail"].lower()


def test_sempipes_info():
    resp = client.get("/api/sempipes-info")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "config" in data


def test_update_config_sets_sempipes_llm_and_temperature():
    """POST /api/update-config calls sempipes.update_config with LLM name and temperature."""
    try:
        import sempipes
        from unittest.mock import patch
    except ImportError:
        pytest.skip("sempipes not available")

    with patch("sempipes.update_config") as mock_update:
        resp = client.post(
            "/api/update-config",
            json={"llm_name": "gemini/gemini-3-flash", "temperature": 0.7},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["llm_name"] == "gemini/gemini-3-flash"
        assert data["temperature"] == 0.7

        # Verify sempipes.update_config was called once with correct LLM object
        assert mock_update.call_count == 1
        call_kwargs = mock_update.call_args.kwargs
        assert "llm_for_code_generation" in call_kwargs
        llm = call_kwargs["llm_for_code_generation"]
        assert llm.name == "gemini/gemini-3-flash"
        assert llm.parameters == {"temperature": 0.7}


def test_update_config_validates_temperature_range():
    """POST /api/update-config rejects temperature values outside 0-2 range."""
    # Test negative temperature
    resp = client.post(
        "/api/update-config",
        json={"llm_name": "gpt-5-mini", "temperature": -0.5},
    )
    assert resp.status_code == 422  # Validation error
    error = resp.json()
    assert "detail" in error

    # Test temperature greater than 2
    resp = client.post(
        "/api/update-config",
        json={"llm_name": "gpt-5-mini", "temperature": 3.0},
    )
    assert resp.status_code == 422
    error = resp.json()
    assert "detail" in error

    # Test valid edge cases
    try:
        import sempipes
        from unittest.mock import patch
    except ImportError:
        pytest.skip("sempipes not available")

    with patch("sempipes.update_config"):
        # Temperature = 0 (minimum)
        resp = client.post(
            "/api/update-config",
            json={"llm_name": "gpt-5-mini", "temperature": 0.0},
        )
        assert resp.status_code == 200

        # Temperature = 2 (maximum)
        resp = client.post(
            "/api/update-config",
            json={"llm_name": "gpt-5-mini", "temperature": 2.0},
        )
        assert resp.status_code == 200

        # Temperature = 1 (middle)
        resp = client.post(
            "/api/update-config",
            json={"llm_name": "gpt-5-mini", "temperature": 1.0},
        )
        assert resp.status_code == 200


def test_generate_returns_200_and_shape():
    resp = client.post(
        "/api/generate",
        json={
            "input_code": "SELECT * FROM t",
            "options": {"optimization_level": 2, "target": "cpp"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "generated_code" in data
    assert "language" in data
    assert data["language"] == "cpp"
    assert "compilation_time_ms" in data
    assert "metadata" in data
    assert "optimizations_applied" in data["metadata"]
    assert "stages" in data["metadata"]
    assert "sempipes_available" in data["metadata"]


def test_generate_default_options():
    resp = client.post("/api/generate", json={"input_code": "x"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "cpp"


def test_compile_returns_200_and_nodes_with_ranges():
    resp = client.post(
        "/api/compile",
        json={"input_code": 'p = pipeline(\n  source("input"),\n  op("transform"),\n)'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    nodes = data["nodes"]
    assert len(nodes) >= 2
    ids = {n["id"] for n in nodes}
    assert "input_input" in ids or any(n["type"] == "input" for n in nodes)
    for n in nodes:
        assert "id" in n and "type" in n and "label" in n
        if n.get("source_range"):
            r = n["source_range"]
            assert "start_line" in r and "start_column" in r and "end_line" in r and "end_column" in r


def test_compile_notebook_style_nodes():
    """Compile recognizes notebook-style patterns (as_X, sem_fillna, sem_choose, etc.)."""
    code = """
basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Binary flag")
products = products.sem_fillna(target_column="make", nl_prompt="Infer manufacturer.")
kept = kept_products.sem_gen_features(nl_prompt="Generate features.", how_many=5)
fraud_detector = augmented_baskets.skb.apply_with_sem_choose(hgb, y=fraud_flags, choices=sem_choose(name="hgb"))
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    assert "edges" in data
    edges = data["edges"]
    assert isinstance(edges, list)
    # Data-flow DAG: edges reflect flow of data, not necessarily a linear chain
    if len(nodes) >= 2:
        assert len(edges) >= 1, "multi-node graph should have at least one edge"
    labels = {n["label"] for n in nodes}
    assert "as_X" in labels
    assert "as_y" in labels
    assert "sem_fillna" in labels
    assert "sem_gen_features" in labels
    assert "apply_with_sem_choose" in labels
    assert "sem_choose" in labels


def test_sempipes_code_generation_uses_mock_no_llm_call():
    """
    When sempipes is available, calling its code-generation path returns
    mocked code; no real LLM is called (we patch _generate_code_from_messages).
    Skipped if sempipes or its deps (e.g. autogluon) are not importable.
    """
    from unittest.mock import patch

    try:
        from sempipes.llm import llm as llm_mod
    except (ImportError, ModuleNotFoundError):
        pytest.skip("sempipes.llm not importable (e.g. missing optional deps)")

    mock_code = "def __sempipes_mock__():\n    return 0"
    messages = [
        {"role": "system", "content": "You generate code."},
        {"role": "user", "content": "Write a function that returns 42."},
    ]
    with patch.object(llm_mod, "_generate_code_from_messages", return_value=mock_code):
        result = llm_mod.generate_python_code_from_messages(messages)
    assert "__sempipes_mock__" in result or "return 0" in result
    assert result.strip(), "mock should return non-empty code"


def test_execute_streams_sse_events():
    """POST /api/execute returns SSE stream with terminal and node_code events. Operator code from pipeline run (mocked stdout)."""
    import json

    resp = client.post(
        "/api/execute",
        json={"input_code": 'basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")\nproducts = products.sem_fillna(target_column="make")'},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    text = resp.text
    assert "terminal" in text
    assert "node_code" in text
    assert "done" in text
    lines = [ln.strip() for ln in text.split("\n") if ln.startswith("data: ")]
    assert len(lines) >= 2
    first = json.loads(lines[0].replace("data: ", ""))
    assert first["type"] == "terminal"
    assert "line" in first


def test_compile_parsed_nodes_have_source_ranges():
    """Design: compile returns source_range for each parsed node (code–graph mapping)."""
    code = "x = sempipes.as_X(df, 'X')\ny = x.sem_fillna(target_column='a')"
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    nodes = resp.json()["nodes"]
    assert len(nodes) >= 2
    for n in nodes:
        assert n.get("source_range") is not None, f"node {n['id']} must have source_range"
        r = n["source_range"]
        assert r["start_line"] >= 1 and r["end_line"] >= 1
        assert r["start_column"] >= 1 and r["end_column"] >= 1


def test_compile_edges_reference_existing_node_ids():
    """Design: every edge source/target must be in nodes (valid DAG)."""
    code = "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data.get("edges", [])
    node_ids = {n["id"] for n in nodes}
    for e in edges:
        assert e["source"] in node_ids, f"edge source {e['source']} not in nodes"
        assert e["target"] in node_ids, f"edge target {e['target']} not in nodes"


def test_validate_graph_json_for_testing_only():
    """Graph validation is for testing only (no public validate endpoint). Validator used internally by compile."""
    from services.graph_validate import validate_graph_json

    valid, errors = validate_graph_json(
        [{"id": "a", "type": "input", "label": "X"}, {"id": "b", "type": "operator", "label": "op"}],
        [{"source": "a", "target": "b"}],
    )
    assert valid is True
    assert errors == []

    valid2, errors2 = validate_graph_json([{"id": "a", "type": "input", "label": "X"}], [{"source": "a", "target": "missing"}])
    assert valid2 is False
    assert any("missing" in e for e in errors2)


def test_compile_skb_eval_has_data_flow_edge():
    """Design: .skb.eval() is a node and receives a data-flow edge from its receiver's producer."""
    code = """
basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
result = basket_ids.skb.eval()
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data.get("edges", [])
    labels = {n["id"]: n["label"] for n in nodes}
    assert "skb.eval" in labels.values()
    skb_eval_id = next(n["id"] for n in nodes if n["label"] == "skb.eval")
    incoming = [e for e in edges if e["target"] == skb_eval_id]
    assert len(incoming) >= 1, "skb.eval should have at least one incoming data-flow edge"


def test_compile_empty_code_returns_fallback_nodes():
    """Design: empty or whitespace code returns fallback input + op nodes and one edge."""
    for code in ("", "   ", "\n\n", "# comment only\n"):
        resp = client.post("/api/compile", json={"input_code": code})
        assert resp.status_code == 200
        data = resp.json()
        nodes = data["nodes"]
        edges = data.get("edges", [])
        assert len(nodes) >= 2, "fallback should have at least input and op"
        assert len(edges) >= 1
        labels = {n["label"] for n in nodes}
        assert "Input" in labels or any(n["type"] == "input" for n in nodes)
        assert "Op" in labels or any(n["type"] == "operator" for n in nodes)


def test_compile_code_with_no_pipeline_nodes_returns_fallback():
    """Design: code with no sempipes/skrub pipeline patterns returns fallback graph."""
    code = "x = 1 + 2\nprint(x)\n# no as_X or sem_fillna"
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data.get("edges", [])
    assert len(nodes) >= 2
    assert len(edges) >= 1


def test_compile_comment_containing_pipeline_word_does_not_create_node():
    """Design: comment text like 'Evaluate the pipeline (materialize result)' must not create a Pipeline node."""
    code = """
basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
# 4) Evaluate the pipeline (materialize result)
result = basket_ids.skb.eval()
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    labels = [n["label"] for n in nodes]
    assert "Pipeline" not in labels, "comment containing 'pipeline (' must not produce a Pipeline node"
    assert "as_X" in labels
    assert "skb.eval" in labels


def test_compile_apply_with_sem_choose_has_edge_from_y():
    """Design: apply_with_sem_choose consumes y= so there is an edge from the as_y producer."""
    code = """
basket_ids = sempipes.as_X(baskets[["ID"]], "X")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")
fraud_detector = augmented_baskets.skb.apply_with_sem_choose(hgb, y=fraud_flags, choices=sem_choose(name="hgb"))
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data.get("edges", [])
    as_y_id = next((n["id"] for n in nodes if n["label"] == "as_y"), None)
    apply_id = next((n["id"] for n in nodes if n["label"] == "apply_with_sem_choose"), None)
    assert as_y_id and apply_id
    edge_from_y = [e for e in edges if e["source"] == as_y_id and e["target"] == apply_id]
    assert len(edge_from_y) >= 1, "apply_with_sem_choose should have incoming edge from as_y (y=)"


def test_execute_stream_emits_skrub_graph_when_runner_returns_svg():
    """When skrub graph runner returns SVG, stream includes skrub_graph event. Subprocess is mocked."""
    import json
    from unittest.mock import MagicMock, patch

    minimal_svg = "<svg xmlns='http://www.w3.org/2000/svg'><text>skrub</text></svg>"

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [minimal_svg.encode("utf-8"), b""]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post(
            "/api/execute",
            json={"input_code": "x = sempipes.as_X(df,'X')"},
        )
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) == 1
    assert skrub_events[0].get("svg", "").strip().startswith("<svg")


def test_execute_stream_no_skrub_graph_when_runner_returns_empty_stdout():
    """When skrub runner returns 0 but empty stdout, stream has no skrub_graph event."""
    import json
    from unittest.mock import MagicMock, patch

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [b""]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post("/api/execute", json={"input_code": "x = sempipes.as_X(df,'X')"})
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) == 0


def test_execute_stream_no_skrub_graph_when_runner_returns_non_svg():
    """When runner stdout does not look like SVG (no leading <), no skrub_graph event."""
    import json
    from unittest.mock import MagicMock, patch

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [b"error: no DataOp", b""]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post("/api/execute", json={"input_code": "x = 1"})
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) == 0


def test_execute_stream_includes_node_code_per_runnable_node():
    """Design: execute stream yields node_code from pipeline run (conftest provides ##SEMPIPES_NODE_CODE## in mock stdout)."""
    import json

    resp = client.post(
        "/api/execute",
        json={"input_code": "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"},
    )
    assert resp.status_code == 200
    text = resp.text
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    assert len(node_code_events) >= 2, "expect at least as_X and sem_fillna"
    for e in node_code_events:
        assert "node_id" in e, "node_code event must have node_id"
        assert "generated_code" in e, "node_code event must have generated_code"
        assert isinstance(e["generated_code"], str)
        assert "retries" in e, "node_code event must include retries"
        assert "cost_usd" in e, "node_code event must include cost_usd"
    # Operator nodes get code from mock runner stdout (##SEMPIPES_NODE_CODE##); no direct LLM call.
    assert any(
        "Simulated sempipes" in e.get("generated_code", "")
        for e in node_code_events
        if e.get("node_id", "").startswith("sem_")
    ), "operator node_code should come from pipeline run (mock stdout)"
    assert any(e["type"] == "done" for e in events)


def test_execute_stream_handles_llm_failure_gracefully():
    """
    When the pipeline run returns no captured operator code (e.g. runner crash, no operators ran),
    operator nodes get placeholder and is_fallback=True — the site must not crash.
    """
    import json
    from unittest.mock import MagicMock, patch

    def _fake_popen_empty_stdout(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [b""]  # no ##SEMPIPES_NODE_CODE##, so no captured codes
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen_empty_stdout):
        resp = client.post(
            "/api/execute",
            json={"input_code": "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"},
        )
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    assert len(node_code_events) >= 2
    operator_events = [e for e in node_code_events if e.get("node_id", "").startswith("sem_")]
    assert len(operator_events) >= 1
    for e in operator_events:
        assert e.get("is_fallback") is True, "operator should get placeholder when no captured code"
        assert "Placeholder" in e.get("generated_code", ""), "fallback code must mention placeholder"
    assert any(e["type"] == "done" for e in events), "stream must always emit done"


def test_execute_stream_includes_input_summary_for_input_nodes():
    """Design: execute stream yields input_summary (schema, sample, row_count) for each input node."""
    import json

    resp = client.post(
            "/api/execute",
            json={"input_code": "sempipes.as_X(df,'X')\nsempipes.as_y(df['y'],'y')\ndf.sem_fillna(target_column='a')"},
        )
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    input_summary_events = [e for e in events if e.get("type") == "input_summary"]
    assert len(input_summary_events) >= 2, "expect at least as_X and as_y input nodes to get input_summary"
    for e in input_summary_events:
        assert "node_id" in e
        assert "schema" in e
        assert "sample" in e
        assert "row_count" in e
        assert isinstance(e["schema"], list)
        assert isinstance(e["sample"], list)
        assert isinstance(e["row_count"], int)
        if e.get("node_id", "").startswith("as_y"):
            assert any(c.get("name") == "target" for c in e["schema"])
        else:
            assert any(c.get("name") == "ID" for c in e["schema"])


def test_execute_stream_includes_cost_and_done_total_cost():
    """Design: execute stream yields cost (total_usd) and done (total_cost_usd). Cost is 0 (LLM runs in subprocess)."""
    import json

    resp = client.post(
        "/api/execute",
        json={"input_code": "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"},
    )
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    cost_events = [e for e in events if e.get("type") == "cost"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(cost_events) >= 1, "stream must include at least one cost event"
    assert cost_events[0].get("total_usd") is not None
    assert len(done_events) >= 1, "stream must include done event"
    assert "total_cost_usd" in done_events[-1], "done event must include total_cost_usd"


def test_compile_exact_nodes_and_edge_chain_for_snippet():
    """Functionality: compile returns exact node count and edges form a linear chain for known code."""
    code = "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data["edges"]
    assert len(nodes) == 2, "expect exactly 2 nodes for as_X + sem_fillna"
    assert len(edges) == 1, "expect exactly 1 edge for 2 nodes"
    assert edges[0]["source"] == nodes[0]["id"]
    assert edges[0]["target"] == nodes[1]["id"]
    assert nodes[0]["label"] == "as_X"
    assert nodes[1]["label"] == "sem_fillna"


def test_execute_node_code_ids_match_compile_runnable_nodes():
    """Functionality: execute stream emits node_code for the same node ids that compile returns."""
    import json

    code = "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"
    compile_resp = client.post("/api/compile", json={"input_code": code})
    assert compile_resp.status_code == 200
    compile_nodes = compile_resp.json()["nodes"]
    runnable_ids = {n["id"] for n in compile_nodes if n["type"] in ("input", "operator")}

    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200
    events = []
    for line in exec_resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    node_code_ids = {e["node_id"] for e in events if e.get("type") == "node_code"}
    assert node_code_ids == runnable_ids, "execute node_code node_ids should match compile runnable nodes"


def test_execute_stream_does_not_call_sempipes_llm_directly():
    """
    Demo must use sempipes API and operators (pipeline run); it must not call
    sempipes.llm.llm.generate_python_code or generate_python_code_from_messages directly.
    """
    pytest.importorskip("sempipes.llm.llm")
    from unittest.mock import patch

    with patch("sempipes.llm.llm.generate_python_code_from_messages") as mock_from_messages:
        with patch("sempipes.llm.llm.generate_python_code") as mock_generate:
            resp = client.post(
                "/api/execute",
                json={"input_code": "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"},
            )
            # execute_stream runs pipeline in subprocess; main process must not call LLM.
            mock_from_messages.assert_not_called()
            mock_generate.assert_not_called()
    assert resp.status_code == 200


def test_execute_stream_uses_captured_code_from_runner_stdout():
    """
    When runner subprocess stdout contains ##SEMPIPES_NODE_CODE## blocks,
    operator nodes get that code (not placeholder) with is_fallback=False.
    This verifies the capture mechanism works: runner patches generate_python_code_from_messages,
    captures operator-generated code, prints it in ##SEMPIPES_NODE_CODE## format,
    and execute_stream parses it and emits node_code events with the captured code.
    """
    import json
    from unittest.mock import MagicMock, patch

    # Runner stdout with two captured codes (for two operator nodes).
    captured_code_1 = "# Real generated code from sem_fillna\ndef fillna_transform(df):\n    df['col'].fillna(0)\n    return df"
    captured_code_2 = "# Real generated code from sem_gen_features\ndef gen_features(df):\n    df['new_feature'] = df['a'] + df['b']\n    return df"

    def _fake_popen_with_captures(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        # Emit ##SEMPIPES_NODE_CODE## blocks as runner would after capturing from operators.
        proc.stdout.readline.side_effect = [
            b"##SEMPIPES_NODE_CODE##\n",
            (json.dumps({"index": 0, "code": captured_code_1}) + "\n").encode("utf-8"),
            b"##END##\n",
            b"##SEMPIPES_NODE_CODE##\n",
            (json.dumps({"index": 1, "code": captured_code_2}) + "\n").encode("utf-8"),
            b"##END##\n",
            b"",  # reader thread stops
        ]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen_with_captures):
        resp = client.post(
            "/api/execute",
            json={"input_code": "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')\ndf.sem_gen_features(target_column='b')"},
        )
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass

    node_code_events = [e for e in events if e.get("type") == "node_code"]
    operator_events = [e for e in node_code_events if e.get("node_id", "").startswith("sem_")]
    assert len(operator_events) >= 2, "expect node_code for sem_fillna and sem_gen_features"

    # First operator (sem_fillna) should have captured_code_1.
    fillna_event = next((e for e in operator_events if "fillna" in e.get("node_id", "")), None)
    assert fillna_event is not None, "should have node_code for sem_fillna"
    assert fillna_event.get("is_fallback") is False, "should use captured code, not fallback"
    assert "Real generated code from sem_fillna" in fillna_event.get("generated_code", "")
    assert "fillna_transform" in fillna_event.get("generated_code", "")

    # Second operator (sem_gen_features) should have captured_code_2.
    gen_features_event = next((e for e in operator_events if "gen_features" in e.get("node_id", "")), None)
    assert gen_features_event is not None, "should have node_code for sem_gen_features"
    assert gen_features_event.get("is_fallback") is False, "should use captured code, not fallback"
    assert "Real generated code from sem_gen_features" in gen_features_event.get("generated_code", "")
    assert "gen_features" in gen_features_event.get("generated_code", "")
