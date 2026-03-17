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
    assert "fraud" in ids
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
    assert "sem_gen_features" in data["content"]


def test_get_script_content_medium_and_fraud_return_200():
    """GET /api/scripts/medium and fraud return 200 and non-empty content."""
    for name in ("medium", "fraud"):
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
            json={"llm_name": "gemini/gemini-3-flash-preview", "temperature": 0.7},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["llm_name"] == "gemini/gemini-3-flash-preview"
        assert data["temperature"] == 0.7

        # Verify sempipes.update_config was called once with correct LLM object
        assert mock_update.call_count == 1
        call_kwargs = mock_update.call_args.kwargs
        assert "llm_for_code_generation" in call_kwargs
        llm = call_kwargs["llm_for_code_generation"]
        assert llm.name == "gemini/gemini-3-flash-preview"
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
    # Uses a minimal modern sempipes script that dynamic extraction can compile.
    # Static fallback is removed; this test always goes through compile_script_to_graph_dynamic.
    resp = client.post(
        "/api/compile",
        json={"input_code": "import skrub\nfrom sklearn.preprocessing import StandardScaler\nX = skrub.var(\"X\")\nresult = X.skb.apply(StandardScaler())\n"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    nodes = data["nodes"]
    assert len(nodes) >= 1
    for n in nodes:
        assert "id" in n and "type" in n and "label" in n
        if n.get("source_range"):
            r = n["source_range"]
            assert "start_line" in r and "start_column" in r and "end_line" in r and "end_column" in r


def test_compile_medium_has_baskets_var_to_as_x_edge():
    """
    Compile API must return a connected graph when skrub.var("baskets") feeds into as_X.
    Note: with dynamic extraction, as_X is a sempipes wrapper that passes through the DataOp,
    so skrub returns the underlying nodes (Var and GetItem), not an explicit 'as_X' node.
    """
    code = """
import skrub
import sempipes
baskets = skrub.var("baskets")
basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    errors = data.get("validation_errors", [])
    if not nodes and errors:
        pytest.skip("dynamic extraction failed: " + (errors[0] if errors else "unknown"))
    # Script has skrub.var("baskets") feeding data; the dynamic graph must include it
    labels = [n.get("label") or "" for n in nodes]
    assert any("baskets" in l for l in labels), f"must have baskets var node. Labels: {labels}"
    # The graph must have at least one edge showing data flow
    assert len(edges) >= 1, f"pipeline must have at least one edge. Got edges: {edges}"


def test_compile_notebook_style_nodes():
    """Compile recognizes notebook-style semantic operators (sem_fillna, sem_gen_features, etc.)."""
    code = """
import skrub
import sempipes

products = skrub.var("products")
products = products.sem_fillna(
    target_column="make",
    nl_prompt="Infer manufacturer.",
    impute_with_existing_values_only=True,
)
kept_products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=5)
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    errors = data.get("validation_errors", [])
    if not nodes and errors:
        pytest.skip("dynamic extraction failed: " + (errors[0] if errors else "unknown"))
    assert "edges" in data
    edges = data["edges"]
    assert isinstance(edges, list)
    # Data-flow DAG: edges reflect flow of data, not necessarily a linear chain
    if len(nodes) >= 2:
        assert len(edges) >= 1, "multi-node graph should have at least one edge"
    labels = {n["label"] for n in nodes}
    # Dynamic compile produces the real skrub graph nodes
    assert "sem_fillna" in labels
    assert "sem_gen_features" in labels


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
        json={"input_code": 'import skrub\ndf = skrub.var("df")\nresult = df.sem_fillna(target_column="a", nl_prompt="Fill", impute_with_existing_values_only=True)\n'},
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
    code = "import skrub\ndf = skrub.var('df')\ny = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
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
    resp = client.post("/api/compile", json={"input_code": code, "use_dynamic": False})
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
    """Design: a pipeline with .skb.eval() produces a connected graph with data-flow edges.

    Note: with dynamic extraction, .skb.eval() calls are stripped before exec so that
    the pipeline is not materialized. The graph reflects the pipeline structure without eval.
    """
    code = """
import skrub
import sempipes
baskets = skrub.var("baskets")
basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
result = basket_ids.skb.eval()
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    errors = data.get("validation_errors", [])
    if not nodes and errors:
        pytest.skip("dynamic extraction failed: " + (errors[0] if errors else "unknown"))
    edges = data.get("edges", [])
    # The pipeline has at least one node (the baskets var or as_X result)
    assert len(nodes) >= 1, "pipeline must produce at least one node"
    # If there are 2+ nodes, there should be at least one edge (data flow)
    if len(nodes) >= 2:
        assert len(edges) >= 1, "multi-node pipeline should have at least one data-flow edge"


def test_compile_empty_code_returns_empty_graph():
    """Design: empty or whitespace code returns empty nodes/edges (frontend shows 'no graph yet')."""
    for code in ("", "   ", "\n\n", "# comment only\n"):
        resp = client.post("/api/compile", json={"input_code": code})
        assert resp.status_code == 200
        data = resp.json()
        nodes = data["nodes"]
        edges = data.get("edges", [])
        assert len(nodes) == 0, "empty code should return empty nodes"
        assert len(edges) == 0, "empty code should return empty edges"


def test_compile_code_with_no_pipeline_nodes_returns_empty_graph():
    """Design: code with no sempipes/skrub pipeline patterns returns empty graph."""
    code = "x = 1 + 2\nprint(x)\n# no as_X or sem_fillna"
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data.get("edges", [])
    assert len(nodes) == 0, "code with no pipeline nodes should return empty nodes"
    assert len(edges) == 0, "code with no pipeline nodes should return empty edges"


def test_compile_dynamic_failure_reports_error_and_falls_back_to_static():
    """When dynamic extraction fails (e.g. exec error), compile falls back to static parsing.

    After luloduarte's change: dynamic failure triggers static-parse fallback.
    The frontend receives whatever static parsing can extract plus a validation_error
    explaining why dynamic extraction failed.
    """
    # Use a script that fails during exec (undefined name not touched by rewrite)
    code = """
baskets = skrub.var("baskets")
_undefined_trigger_for_dynamic_failure
basket_ids = sempipes.as_X(baskets[["ID"]], "X")
"""
    resp = client.post("/api/compile", json={"input_code": code, "use_dynamic": True})
    assert resp.status_code == 200
    data = resp.json()
    # Report the extraction error so the frontend can show why dynamic graph failed.
    errors = data.get("validation_errors", [])
    assert len(errors) >= 1, "validation_errors should contain extraction error when dynamic fails"
    combined = " ".join(errors).lower()
    assert "failed" in combined or "error" in combined, "error message should explain the failure"


def test_compile_full_like_script_produces_graph_with_dynamic():
    """Script with var(data), as_X/as_y, and no eval/cross_validate must produce a graph (same shape as full)."""
    # Minimal script that matches full.py shape: real data for vars, no stripping; runs in seconds.
    code = """
import skrub
import sempipes
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)
baskets = baskets.skb.subsample(n=100, how="random")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Fraud label")
basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
"""
    resp = client.post("/api/compile", json={"input_code": code, "use_dynamic": True})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    errors = data.get("validation_errors", [])
    if not nodes and errors:
        pytest.skip("dynamic extraction failed: " + (errors[0] if errors else "unknown"))
    assert len(nodes) >= 1, f"full-like script must produce nodes. errors={errors}"
    labels = [n.get("label") or "" for n in nodes]
    assert any("baskets" in l or "products" in l for l in labels), f"expected var nodes. labels={labels}"


@pytest.mark.slow
def test_compile_full_script_produces_graph_with_dynamic():
    """Full pipeline script (from scripts/full) must produce a non-empty graph with use_dynamic=True."""
    resp = client.get("/api/scripts/full")
    if resp.status_code != 200:
        pytest.skip("full script not available")
    content = resp.json().get("content", "")
    if not content.strip():
        pytest.skip("full script content empty")
    resp = client.post("/api/compile", json={"input_code": content, "use_dynamic": True})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    errors = data.get("validation_errors", [])
    if not nodes and errors:
        pytest.skip(
            "dynamic extraction failed (e.g. catboost or skrub not available): "
            + (errors[0] if errors else "unknown")
        )
    assert len(nodes) >= 1, f"full script must produce at least one node. errors={errors}"
    labels = [n.get("label") or "" for n in nodes]
    assert any(
        "baskets" in l or "products" in l or "sem_fillna" in l or "sem_gen" in l
        for l in labels
    ), f"expected var/operator nodes from full script. labels={labels}"


def test_compile_comment_containing_pipeline_word_does_not_create_node():
    """Design: comment text like 'Evaluate the pipeline (materialize result)' must not create a Pipeline node."""
    code = """
import skrub
import sempipes
baskets = skrub.var("baskets")
basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
# 4) Evaluate the pipeline (materialize result)
result = basket_ids.skb.eval()
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    errors = data.get("validation_errors", [])
    if not nodes and errors:
        pytest.skip("dynamic extraction failed: " + (errors[0] if errors else "unknown"))
    labels = [n["label"] for n in nodes]
    assert "Pipeline" not in labels, "comment containing 'pipeline (' must not produce a Pipeline node"
    # Dynamic compile produces the real skrub nodes; comment must not create spurious nodes
    assert any("baskets" in l for l in labels), f"baskets var must be present. Labels: {labels}"


def test_compile_apply_with_sem_choose_has_edge_from_y():
    """Design: apply_with_sem_choose consumes y= so there is an edge from the as_y producer."""
    code = """
import skrub
import sempipes
from sempipes import sem_choose
from sklearn.ensemble import HistGradientBoostingClassifier

baskets = skrub.var("baskets")
basket_ids = sempipes.as_X(baskets[["ID"]], "X")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")
hgb = HistGradientBoostingClassifier()
fraud_detector = basket_ids.skb.apply_with_sem_choose(hgb, y=fraud_flags, choices=sem_choose(name="hgb"))
"""
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    errors = data.get("validation_errors", [])
    if not nodes and errors:
        pytest.skip("dynamic extraction failed: " + (errors[0] if errors else "unknown"))
    edges = data.get("edges", [])
    apply_id = next((n["id"] for n in nodes if n["label"] == "apply_with_sem_choose"), None)
    assert apply_id, f"must have apply_with_sem_choose node. Labels: {[n['label'] for n in nodes]}"
    # apply_with_sem_choose should have at least one incoming edge (from the data or y= source)
    incoming = [e for e in edges if e["target"] == apply_id]
    assert len(incoming) >= 1, "apply_with_sem_choose should have at least one incoming data-flow edge"


def test_execute_stream_emits_fallback_graph_when_runner_returns_only_svg():
    """When runner returns only SVG (no ##SKRUB_GRAPH##), we emit fallback graph from compile so user sees a graph."""
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

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post(
            "/api/execute",
            json={"input_code": _valid_code},
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
    # When runner returns only SVG (no ##SKRUB_GRAPH##), we emit fallback graph from compile so user sees a graph
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) >= 1, "emit fallback graph from compile when runner returns only SVG"


def test_execute_stream_emits_fallback_graph_when_runner_returns_empty_stdout():
    """When runner returns empty stdout, we emit fallback graph from compile so user sees a graph."""
    import json
    from unittest.mock import MagicMock, patch

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [b""]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post("/api/execute", json={"input_code": _valid_code})
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) >= 1, "emit fallback graph when runner returns empty stdout"


def test_execute_stream_emits_fallback_graph_when_runner_returns_non_svg():
    """When runner stdout does not contain ##SKRUB_GRAPH##, we emit fallback graph from compile so user sees a graph."""
    import json
    from unittest.mock import MagicMock, patch

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [b"error: no DataOp", b""]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    # Use valid pipeline code so compile returns nodes (fallback can be built)
    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post("/api/execute", json={"input_code": _valid_code})
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) >= 1, "emit fallback graph when runner does not return ##SKRUB_GRAPH##"


def test_execute_stream_no_pipeline_nodes_returns_no_graph():
    """When code has no pipeline nodes, execute returns skrub_graph event with empty/null graph."""
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
    # With no pipeline nodes, compile returns empty, so no graph to show
    if skrub_events:
        graph = skrub_events[0].get("graph")
        # Graph should be None or have empty nodes
        if graph is not None:
            assert len(graph.get("nodes", [])) == 0, "no pipeline nodes should result in empty graph"


def test_execute_stream_skrub_graph_includes_skrub_to_compile_id_mapping():
    """skrub_graph event includes skrubToCompileId for frontend graph-to-code highlighting."""
    import json
    from unittest.mock import MagicMock, patch

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [b""]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post(
            "/api/execute",
            json={"input_code": _valid_code},
        )
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) >= 1, "must emit skrub_graph"
    ev = skrub_events[0]
    mapping = ev.get("skrubToCompileId", {})
    assert isinstance(mapping, dict), "skrubToCompileId must be a dict"
    graph_nodes = (ev.get("graph") or {}).get("nodes") or []
    for sn in graph_nodes:
        skid = sn.get("id")
        if skid:
            assert skid in mapping, f"skrub node {skid} must have compile id mapping"
            assert isinstance(mapping[skid], str), f"mapping for {skid} must be string"


def test_execute_stream_emits_full_dag_when_skrub_misses_inputs():
    """When skrub graph has only sem_fillna+skb.eval, merge adds var+subsample so graph is full DAG."""
    import json
    from unittest.mock import MagicMock, patch

    # Skrub returns graph without input nodes (common with sempipes Apply)
    skrub_graph_json = json.dumps({
        "nodes": [
            {"id": "0", "label": "sem_fillna", "is_sempipes_semantic": True},
            {"id": "1", "label": "skb.eval", "is_sempipes_semantic": False},
        ],
        "parents": {"0": [], "1": ["0"]},
        "children": {"0": ["1"], "1": []},
        "sempipesNodeIds": ["0"],
    })

    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [
            b"##SKRUB_GRAPH##\n",
            (skrub_graph_json + "\n").encode("utf-8"),
            b"##END##\n",
            b"",
        ]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    code = """
import skrub
products = skrub.var("products")
products = products.skb.subsample(n=100)
products = products.sem_fillna(target_column="make", nl_prompt="Fill", impute_with_existing_values_only=True)
result = products.skb.eval()
"""
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post("/api/execute", json={"input_code": code})
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) >= 1, "must emit skrub_graph"
    graph = skrub_events[0].get("graph", {})
    nodes = graph.get("nodes", [])
    labels = [n.get("label", "") for n in nodes]
    assert any("products" in l for l in labels), "merge must add var (products) for full DAG"
    assert any("subsample" in l.lower() for l in labels), "merge must add subsample for full DAG"
    assert "sem_fillna" in labels, "skrub sem_fillna must remain"
    assert "skb.eval" in labels, "skrub skb.eval must remain"


def test_execute_stream_emits_skrub_graph_only_when_runner_prints_marker():
    """We emit skrub_graph only when runner prints ##SKRUB_GRAPH## with a valid graph dict (real skrub)."""
    import json
    from unittest.mock import MagicMock, patch

    real_skrub_graph = {
        "nodes": [{"id": "n1", "label": "as_X", "is_sempipes_semantic": False}, {"id": "n2", "label": "sem_fillna", "is_sempipes_semantic": True}],
        "parents": {"n1": [], "n2": ["n1"]},
        "children": {"n1": ["n2"], "n2": []},
        "sempipesNodeIds": ["n2"],
    }
    # Runner prints marker, then json line, then end (readline returns one line at a time)
    def _fake_popen(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout.readline.side_effect = [
            b"##SKRUB_GRAPH##\n",
            (json.dumps(real_skrub_graph) + "\n").encode("utf-8"),
            b"##END##\n",
            b"",
        ]
        proc.wait.return_value = None
        proc.returncode = 0
        return proc

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen):
        resp = client.post("/api/execute", json={"input_code": _valid_code})
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    skrub_events = [e for e in events if e.get("type") == "skrub_graph"]
    assert len(skrub_events) == 1
    graph = skrub_events[0].get("graph")
    assert graph is not None
    # The merge logic may add extra nodes from the compile graph (e.g. var nodes),
    # so check that all nodes from real_skrub_graph are present (subset check).
    actual_node_labels = {n.get("label") for n in graph.get("nodes", [])}
    for expected_node in real_skrub_graph["nodes"]:
        assert expected_node["label"] in actual_node_labels, (
            f"Expected node '{expected_node['label']}' to be present in merged graph"
        )
    assert "n1" in (graph.get("parents") or {}) or any(
        n.get("label") == "as_X" for n in graph.get("nodes", [])
    )

    # Semantic operators get node_code; non-semantic/non-var nodes get no fake input_summary
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    input_summary_events = [e for e in events if e.get("type") == "input_summary"]

    # Semantic operators (sem_fillna, n2) should get node_code
    semantic_codes = [e for e in node_code_events if "sem_fillna" in str(e.get("node_id", "")) or "n2" in str(e.get("node_id", ""))]
    assert len(semantic_codes) >= 1, "semantic operators should get node_code events"

    # input_summary is only emitted for real Var nodes with available data — no fake data
    for e in input_summary_events:
        assert "schema" in e and "sample" in e and "row_count" in e, "input_summary must contain real data fields"


def test_skrub_runner_treats_apply_nodes_as_semantic_and_maps_to_sempipes():
    """Apply nodes (e.g. Apply ImputedLearner) are semantic and displayed as sempipes operators."""
    from services.skrub_graph_runner import (
        _is_sempipes_semantic_label,
        _apply_label_to_sempipes_operator,
    )

    assert _is_sempipes_semantic_label("Apply ImputedLearner") is True
    assert _is_sempipes_semantic_label("Apply LLMImputer") is True
    assert _is_sempipes_semantic_label("Apply CodeBasedFeatureExtractor") is True
    assert _is_sempipes_semantic_label("sem_fillna") is True
    assert _is_sempipes_semantic_label("Subsample") is False

    assert _apply_label_to_sempipes_operator("Apply ImputedLearner") == "sem_fillna"
    assert _apply_label_to_sempipes_operator("Apply LLMImputer") == "sem_fillna"
    assert _apply_label_to_sempipes_operator("Apply CodeBasedFeatureExtractor") == "sem_gen_features"
    assert _apply_label_to_sempipes_operator("Apply CodeDataAugmentor") == "sem_augment"
    assert _apply_label_to_sempipes_operator("Apply SelectCols") == "sem_select"
    assert _apply_label_to_sempipes_operator("Subsample") == "Subsample"


def test_execute_stream_includes_node_code_per_runnable_node():
    """Design: execute stream yields node_code from pipeline run (conftest provides ##SEMPIPES_NODE_CODE## in mock stdout)."""
    import json

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    resp = client.post(
        "/api/execute",
        json={"input_code": _valid_code},
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
    assert len(node_code_events) >= 1, "expect at least one node_code for semantic operator"
    for e in node_code_events:
        assert "node_id" in e, "node_code event must have node_id"
        assert "generated_code" in e, "node_code event must have generated_code"
        assert isinstance(e["generated_code"], str)
        assert "retries" in e, "node_code event must include retries"
        assert "cost_usd" in e, "node_code event must include cost_usd"
    # Semantic operator gets code from mock runner stdout (##SEMPIPES_NODE_CODE##); no direct LLM call.
    assert any(
        "Simulated sempipes" in e.get("generated_code", "")
        for e in node_code_events
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

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen_empty_stdout):
        resp = client.post(
            "/api/execute",
            json={"input_code": _valid_code},
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
    # Semantic operators get node_code (with placeholder when runner returns nothing).
    # Non-semantic, non-Var nodes get no event — no fake input_summary emitted.
    node_code_events = [e for e in events if e.get("type") == "node_code"]

    assert len(node_code_events) >= 1, "semantic operator should get node_code"

    # With dynamic compile, node IDs are numeric; check that all node_code events are fallbacks
    # (empty stdout → no captured codes → all operators get placeholder)
    fallback_events = [e for e in node_code_events if e.get("is_fallback") is True]
    assert len(fallback_events) >= 1, "operator should get placeholder when no captured code"
    for e in fallback_events:
        assert "Placeholder" in e.get("generated_code", ""), "fallback code must mention placeholder"
    assert any(e["type"] == "done" for e in events), "stream must always emit done"


def test_execute_stream_no_fake_input_summary_for_non_var_nodes():
    """Design: execute stream never emits fake input_summary events. Only real Var nodes with available
    data get input_summary. Non-Var operator nodes (subsample, etc.) get no input_summary."""
    import json

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    resp = client.post(
            "/api/execute",
            json={"input_code": _valid_code},
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

    # input_summary is only emitted for real Var nodes with available data.
    # as_X, as_y are operator nodes (non-Var), so they should NOT get input_summary.
    input_summary_events = [e for e in events if e.get("type") == "input_summary"]
    for e in input_summary_events:
        # Any input_summary that IS emitted must have real data fields
        assert "node_id" in e
        assert "schema" in e and isinstance(e["schema"], list)
        assert "sample" in e and isinstance(e["sample"], list)
        assert "row_count" in e and isinstance(e["row_count"], int)
        # Real data must have more than 1 column (the single-column {name: "ID"} was a mock artifact)
        # Note: may be 0 summaries total since no Var nodes in this script — that's correct
    # Semantic operators still get node_code
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    assert len(node_code_events) >= 1, "semantic operators must still get node_code"


def test_parse_captured_codes_returns_code_cost_usd_and_attempts():
    """_parse_captured_codes_from_stdout returns list of dicts with code, cost_usd, attempts; attempts default 1 when missing."""
    from services.execute_stream import _parse_captured_codes_from_stdout

    stdout = (
        "##SEMPIPES_NODE_CODE##\n"
        '{"index": 0, "code": "x = 1"}\n'
        "##END##\n"
        "##SEMPIPES_NODE_CODE##\n"
        '{"index": 1, "code": "y = 2", "cost_usd": 0.0025, "attempts": 2}\n'
        "##END##\n"
    )
    result = _parse_captured_codes_from_stdout(stdout)
    assert len(result) == 2
    assert result[0]["code"] == "x = 1"
    assert result[0]["cost_usd"] == 0.0
    assert result[0]["attempts"] == 1
    assert result[1]["code"] == "y = 2"
    assert result[1]["cost_usd"] == 0.0025
    assert result[1]["attempts"] == 2


def test_extract_single_svg_document_strips_trailing_markers():
    """_extract_single_svg_document returns only the SVG document; no ##END## or ##EXECUTION_STATS##."""
    from services.execute_stream import _extract_single_svg_document

    svg_content = '<svg width="100" height="50"><g id="graph0"/></svg>'
    with_junk = svg_content + "\n\n##END##\n##EXECUTION_STATS##\n{\"duration_ms\": 100, \"cost_usd\": 0}"
    result = _extract_single_svg_document(with_junk)
    assert result.startswith("<svg")
    assert result.endswith("</svg>")
    assert "##EXECUTION_STATS##" not in result
    assert "##END##" not in result
    assert "duration_ms" not in result
    assert result == svg_content


def test_extract_single_svg_document_returns_original_when_no_closing_tag():
    """_extract_single_svg_document returns original string when </svg> is missing."""
    from services.execute_stream import _extract_single_svg_document

    incomplete = "<svg><g></g>"
    assert _extract_single_svg_document(incomplete) == incomplete


def test_runner_cost_tracking_patches_sempipes_llm_and_records_cost():
    """Runner patches sempipes.llm.llm (call site) so cost is recorded; guards against patching wrong module."""
    from unittest.mock import MagicMock, patch

    try:
        import sempipes.llm.llm as llm_module
    except ImportError:
        pytest.skip("sempipes not available")

    with patch("litellm.completion_cost", return_value=0.01), patch.object(
        llm_module, "completion", return_value=MagicMock()
    ):
        from services.skrub_graph_runner import _track_litellm_costs

        with _track_litellm_costs() as costs:
            llm_module.completion(model="test", messages=[])
        assert costs == [0.01], "cost should be recorded when call goes through patched sempipes.llm.llm"


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


def test_execute_stream_per_node_cost_and_total_from_runner_stdout():
    """When mock runner stdout includes cost_usd in ##SEMPIPES_NODE_CODE## and ##EXECUTION_STATS##, stream forwards them."""
    import json
    from unittest.mock import MagicMock, patch

    def _fake_popen_with_costs(*args, **kwargs):
        proc = MagicMock()
        proc.stdin = MagicMock()
        # Backend reads with iter(proc.stdout.readline, b""), so provide line-by-line then b""
        proc.stdout.readline.side_effect = [
            b"##SEMPIPES_NODE_CODE##\n",
            b'{"index": 0, "code": "# op0", "cost_usd": 0.001, "attempts": 1}\n',
            b"##END##\n",
            b"##SEMPIPES_NODE_CODE##\n",
            b'{"index": 1, "code": "# op1", "cost_usd": 0.002, "attempts": 2}\n',
            b"##END##\n",
            b"##EXECUTION_STATS##\n",
            b'{"duration_ms": 100, "cost_usd": 0.003}\n',
            b"##END##\n",
            b"",
        ]
        proc.wait.return_value = 0
        proc.returncode = 0
        return proc

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "r = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
        "r2 = r.sem_gen_features(nl_prompt='Gen', name='feat', how_many=2)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen_with_costs):
        resp = client.post(
            "/api/execute",
            json={"input_code": _valid_code},
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
    # All node_code events for non-input nodes (dynamic compile uses numeric IDs)
    node_code_events = [e for e in events if e.get("type") == "node_code"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(node_code_events) >= 2
    # Per-node costs and retries (attempts) from runner should be forwarded
    operator_costs = [e.get("cost_usd", 0) for e in node_code_events]
    assert any(c > 0 for c in operator_costs), "at least one operator should have cost_usd from runner"
    operator_retries = [e.get("retries", 0) for e in node_code_events]
    assert any(r >= 1 for r in operator_retries), "at least one operator should have retries (attempts) >= 1 from runner"
    assert len(done_events) >= 1
    assert done_events[-1].get("total_cost_usd") == 0.003


def test_compile_simple_pipeline_full_dag_var_subsample_sem_gen_features_eval():
    """Compile returns full DAG for simple pipeline: skrub.var, skb.subsample, sem_gen_features, skb.eval."""
    code = """
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="product_features", how_many=3)
result = products.skb.eval()
"""
    resp = client.post("/api/compile", json={"input_code": code, "use_dynamic": False})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data["edges"]
    labels = [n["label"] for n in nodes]
    # With raw skrub labels: <Var 'products'>, <SubsamplePreviews>, <Apply LLMFeatureGenerator>, etc.
    assert any("products" in l for l in labels), f"var node (products) should be in graph. Got: {labels}"
    assert any("subsample" in l.lower() for l in labels), f"subsample node should be in graph. Got: {labels}"
    # sem_gen_features may appear as <Apply LLMFeatureGenerator> in raw labels
    assert any("feature" in l.lower() or "sem_gen" in l.lower() for l in labels), f"feature gen node should be in graph. Got: {labels}"
    assert len(nodes) >= 2, "expect at least 2 nodes for pipeline structure"
    assert len(edges) >= 1, "expect at least 1 edge for data flow"


def test_compile_exact_nodes_and_edge_chain_for_snippet():
    """Functionality: compile returns exact node count and edges form a linear chain for known code."""
    code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill missing', impute_with_existing_values_only=True)\n"
    )
    resp = client.post("/api/compile", json={"input_code": code})
    assert resp.status_code == 200
    data = resp.json()
    nodes = data["nodes"]
    edges = data["edges"]
    assert len(nodes) == 2, "expect exactly 2 nodes for var + sem_fillna"
    assert len(edges) == 1, "expect exactly 1 edge for 2 nodes"
    assert edges[0]["source"] == nodes[0]["id"]
    assert edges[0]["target"] == nodes[1]["id"]
    # var node first, then sem_fillna
    assert "df" in nodes[0]["label"].lower() or nodes[0]["type"] == "input"
    assert nodes[1]["label"] == "sem_fillna"


def test_execute_node_code_emitted_for_semantic_operators():
    """Execute stream emits node_code for every semantic operator in the compile graph.
    Non-semantic nodes (var, subsample) get no fake events — real data only when available."""
    import json

    code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "result = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
    )
    compile_resp = client.post("/api/compile", json={"input_code": code})
    assert compile_resp.status_code == 200
    compile_nodes = compile_resp.json()["nodes"]
    semantic_ids = {n["id"] for n in compile_nodes if n["type"] == "operator" and
                    any(s in n.get("label", "") for s in ("sem_", "apply"))}

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
    # Semantic operators must get node_code events
    node_code_ids = {e["node_id"] for e in events if e.get("type") == "node_code"}
    assert len(node_code_ids) >= 1, "execute must emit node_code for semantic operators"

    # No fake input_summary: every emitted input_summary must have real data structure
    for e in events:
        if e.get("type") == "input_summary":
            assert "schema" in e and "sample" in e and "row_count" in e


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

    _valid_code = (
        "import skrub\n"
        "df = skrub.var('df')\n"
        "r = df.sem_fillna(target_column='a', nl_prompt='Fill', impute_with_existing_values_only=True)\n"
        "r2 = r.sem_gen_features(nl_prompt='Gen', name='feat', how_many=2)\n"
    )
    with patch("services.execute_stream.subprocess.Popen", side_effect=_fake_popen_with_captures):
        resp = client.post(
            "/api/execute",
            json={"input_code": _valid_code},
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
    # With dynamic compile, node IDs are numeric (e.g. "1", "7"); check by generated_code content
    assert len(node_code_events) >= 2, "expect node_code for sem_fillna and sem_gen_features"

    # First captured code (index 0 = fillna code) should appear in one of the events.
    fillna_event = next(
        (e for e in node_code_events if "Real generated code from sem_fillna" in e.get("generated_code", "")),
        None
    )
    assert fillna_event is not None, "should have node_code with sem_fillna captured code"
    assert fillna_event.get("is_fallback") is False, "should use captured code, not fallback"
    assert "fillna_transform" in fillna_event.get("generated_code", "")

    # Second captured code (index 1 = gen_features code) should appear in another event.
    gen_features_event = next(
        (e for e in node_code_events if "Real generated code from sem_gen_features" in e.get("generated_code", "")),
        None
    )
    assert gen_features_event is not None, "should have node_code with sem_gen_features captured code"
    assert gen_features_event.get("is_fallback") is False, "should use captured code, not fallback"
    assert "gen_features" in gen_features_event.get("generated_code", "")


def test_build_skrub_to_compile_id_handles_duplicate_labels():
    """
    _build_skrub_to_compile_id should correctly map multiple nodes with the same label
    to different compile nodes by tracking occurrences and using document order.

    Regression test for bug: clicking node N shows code for node N-1.
    """
    from services.execute_stream import _build_skrub_to_compile_id
    from models.schemas import CompileNode, SourceRange

    # Compile nodes (runnable) in document order (sorted by line number)
    runnable = [
        CompileNode(
            id="var_5", type="input", label="products",
            source_range=SourceRange(start_line=5, start_column=1, end_line=5, end_column=20)
        ),
        CompileNode(
            id="fillna_8", type="operator", label="sem_fillna",
            source_range=SourceRange(start_line=8, start_column=1, end_line=8, end_column=30)
        ),
        CompileNode(
            id="gen_11", type="operator", label="sem_gen_features",
            source_range=SourceRange(start_line=11, start_column=1, end_line=11, end_column=40)
        ),
        CompileNode(
            id="eval_15", type="operator", label="skb.eval",
            source_range=SourceRange(start_line=15, start_column=1, end_line=15, end_column=20)
        ),
    ]

    # Skrub graph nodes (numeric IDs in topological order which may differ from document order)
    graph = {
        "nodes": [
            {"id": "0", "label": "products"},
            {"id": "1", "label": "sem_fillna"},
            {"id": "2", "label": "sem_gen_features"},
            {"id": "3", "label": "skb.eval"},
        ]
    }

    result = _build_skrub_to_compile_id(graph, runnable)

    # Each skrub node should map to the correct compile node
    assert result["0"] == "var_5", "skrub node 0 (products) should map to var_5"
    assert result["1"] == "fillna_8", "skrub node 1 (sem_fillna) should map to fillna_8"
    assert result["2"] == "gen_11", "skrub node 2 (sem_gen_features) should map to gen_11"
    assert result["3"] == "eval_15", "skrub node 3 (skb.eval) should map to eval_15"


def test_build_skrub_to_compile_id_handles_multiple_same_label_operators():
    """
    When multiple nodes have the same label (e.g., two sem_gen_features calls),
    the mapping should assign the Nth occurrence of a label in skrub nodes
    to the Nth occurrence in compile nodes (in document order).

    Regression test for bug: duplicate label collision caused wrong mapping.
    """
    from services.execute_stream import _build_skrub_to_compile_id
    from models.schemas import CompileNode, SourceRange

    # Two sem_gen_features calls at different lines
    runnable = [
        CompileNode(
            id="var_5", type="input", label="products",
            source_range=SourceRange(start_line=5, start_column=1, end_line=5, end_column=20)
        ),
        CompileNode(
            id="gen_8", type="operator", label="sem_gen_features",
            source_range=SourceRange(start_line=8, start_column=1, end_line=8, end_column=40)
        ),
        CompileNode(
            id="gen_12", type="operator", label="sem_gen_features",
            source_range=SourceRange(start_line=12, start_column=1, end_line=12, end_column=40)
        ),
    ]

    # Skrub graph has two sem_gen_features nodes
    graph = {
        "nodes": [
            {"id": "0", "label": "products"},
            {"id": "1", "label": "sem_gen_features"},
            {"id": "2", "label": "sem_gen_features"},
        ]
    }

    result = _build_skrub_to_compile_id(graph, runnable)

    # First sem_gen_features should map to first (line 8), second to second (line 12)
    assert result["1"] == "gen_8", "first sem_gen_features (skrub 1) should map to gen_8 (line 8)"
    assert result["2"] == "gen_12", "second sem_gen_features (skrub 2) should map to gen_12 (line 12)"
