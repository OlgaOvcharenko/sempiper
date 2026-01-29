import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


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


def test_generate_default_options():
    resp = client.post("/api/generate", json={"input_code": "x"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "cpp"
