"""
Demo backend tests.

We keep tests close to sempipes but NEVER call real LLMs. We simulate correct
behaviour via mocks:

- conftest.py: patches litellm.completion / batch_completion when available.
- Execute tests (test_execute_streams_sse_events, test_execute_stream_includes_
  node_code_per_runnable_node): patch services.execute_stream._generate_code_
  via_sempipes to return fixed code so the execute stream never calls the
  sempipes LLM; we assert the stream contains the mocked code.
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


def test_sempipes_info():
    resp = client.get("/api/sempipes-info")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "config" in data


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
    if len(nodes) >= 2:
        assert len(edges) == len(nodes) - 1
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
    """POST /api/execute returns SSE stream with terminal and node_code events. LLM is mocked."""
    import json
    from unittest.mock import patch

    # Mock code generation so we never call sempipes LLM; simulate correct behaviour.
    mock_code = "# Mocked generated code (no real LLM call)\ndef step(): return result"
    with patch(
        "services.execute_stream._generate_code_via_sempipes",
        return_value=mock_code,
    ):
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


def test_execute_stream_includes_node_code_per_runnable_node():
    """Design: execute stream yields node_code with node_id and generated_code. LLM is mocked."""
    import json
    from unittest.mock import patch

    # Mock sempipes LLM so we never call it; simulate that code generation succeeds.
    mock_code = "# Simulated sempipes code (no real LLM call)\nresult = process(data)"
    with patch(
        "services.execute_stream._generate_code_via_sempipes",
        return_value=mock_code,
    ):
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
    # When mocked, operator nodes get our simulated code (sempipes path never called).
    assert any(
        "Simulated sempipes" in e.get("generated_code", "")
        for e in node_code_events
        if e.get("node_id", "").startswith("sem_")
    ), "operator node_code should contain mocked code when LLM is patched"
    assert any(e["type"] == "done" for e in events)
