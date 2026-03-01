"""
Tests for the optimizer trajectory API router (/api/optimizer/).

These tests patch SEARCH_PATHS in the router module to point at a temporary
directory, so no real .sempipes_trajectories files are required and no LLMs
are called.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def traj_dir(tmp_path):
    """Temporary directory used as the sole trajectory search path."""
    d = tmp_path / ".sempipes_trajectories"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def patch_search_paths(traj_dir, monkeypatch):
    """Redirect SEARCH_PATHS in the optimizer router to the temp directory."""
    import routers.optimizer as opt_module
    monkeypatch.setattr(opt_module, "SEARCH_PATHS", [traj_dir])


SAMPLE_TRAJECTORY = {
    "optimizer_args": {"scoring": "roc_auc"},
    "outcomes": [
        {"search_node": {"trial": 0, "parent_trial": None}, "score": 0.75, "state": {"generated_code": "x = 1"}},
        {"search_node": {"trial": 1, "parent_trial": 0}, "score": 0.82, "state": {"generated_code": "x = 2"}},
    ],
}


# ---------------------------------------------------------------------------
# /api/optimizer/status
# ---------------------------------------------------------------------------

def test_status_returns_false_when_no_files(client):
    resp = client.get("/api/optimizer/status")
    assert resp.status_code == 200
    assert resp.json() == {"active": False}


def test_status_returns_true_when_file_exists(client, traj_dir):
    (traj_dir / "optimise_house_simulated.json").write_text(json.dumps(SAMPLE_TRAJECTORY))
    resp = client.get("/api/optimizer/status")
    assert resp.status_code == 200
    assert resp.json() == {"active": True}


# ---------------------------------------------------------------------------
# /api/optimizer/latest
# ---------------------------------------------------------------------------

def test_latest_returns_404_when_no_files(client):
    resp = client.get("/api/optimizer/latest")
    assert resp.status_code == 404


def test_latest_returns_newest_file(client, traj_dir):
    first = traj_dir / "run_a.json"
    first.write_text(json.dumps({"outcomes": [{"score": 0.5}]}))
    time.sleep(0.01)
    second = traj_dir / "run_b.json"
    second.write_text(json.dumps(SAMPLE_TRAJECTORY))

    resp = client.get("/api/optimizer/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run_b.json"
    assert "outcomes" in data


def test_latest_injects_run_id(client, traj_dir):
    (traj_dir / "my_run.json").write_text(json.dumps(SAMPLE_TRAJECTORY))
    resp = client.get("/api/optimizer/latest")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "my_run.json"


# ---------------------------------------------------------------------------
# /api/optimizer/by-script
# ---------------------------------------------------------------------------

def test_by_script_returns_404_when_no_match(client):
    resp = client.get("/api/optimizer/by-script?script_id=nonexistent")
    assert resp.status_code == 404


def test_by_script_returns_matching_file(client, traj_dir):
    (traj_dir / "optimise_house_simulated.json").write_text(json.dumps(SAMPLE_TRAJECTORY))
    resp = client.get("/api/optimizer/by-script?script_id=optimise_house")
    assert resp.status_code == 200
    data = resp.json()
    assert "outcomes" in data
    assert data["run_id"] == "optimise_house_simulated.json"


def test_by_script_strips_py_extension(client, traj_dir):
    (traj_dir / "optimise_fraud_simulated.json").write_text(json.dumps(SAMPLE_TRAJECTORY))
    resp = client.get("/api/optimizer/by-script?script_id=optimise_fraud.py")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "optimise_fraud_simulated.json"


def test_by_script_picks_newest_when_multiple(client, traj_dir):
    old = traj_dir / "optimise_house_run1.json"
    old.write_text(json.dumps({"outcomes": [{"score": 0.5}], "tag": "old"}))
    time.sleep(0.01)
    new = traj_dir / "optimise_house_run2.json"
    new.write_text(json.dumps({"outcomes": [{"score": 0.9}], "tag": "new"}))

    resp = client.get("/api/optimizer/by-script?script_id=optimise_house")
    assert resp.status_code == 200
    assert resp.json()["tag"] == "new"


# ---------------------------------------------------------------------------
# /api/optimizer/by-label
# ---------------------------------------------------------------------------

def test_by_label_returns_404_when_no_match(client):
    resp = client.get("/api/optimizer/by-label?label=nonexistent_label")
    assert resp.status_code == 404


def test_by_label_returns_matching_file(client, traj_dir):
    (traj_dir / "optimise_museums_simulated.json").write_text(json.dumps(SAMPLE_TRAJECTORY))
    resp = client.get("/api/optimizer/by-label?label=museums")
    assert resp.status_code == 200
    data = resp.json()
    assert "outcomes" in data
    assert data["run_id"] == "optimise_museums_simulated.json"
