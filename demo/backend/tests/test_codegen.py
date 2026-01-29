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
