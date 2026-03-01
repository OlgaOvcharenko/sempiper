"""
Tests for the optimizer trajectory API router (/api/optimizer/).

Fixtures redirect both SEARCH_PATHS (legacy directory fallback) and
_trajectory_cache (primary CacheService store) to temporary directories,
so no real .sempipes_trajectories files or .cache entries are required
and no LLMs are called.
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
    """Temporary directory used as the sole legacy trajectory search path."""
    d = tmp_path / ".sempipes_trajectories"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def patch_optimizer_stores(traj_dir, tmp_path, monkeypatch):
    """Redirect SEARCH_PATHS and _trajectory_cache to temp directories."""
    import routers.optimizer as opt_module
    from services.cache.cache_service import CacheService

    monkeypatch.setattr(opt_module, "SEARCH_PATHS", [traj_dir])
    temp_cache = CacheService(tmp_path / ".cache/optimizer")
    monkeypatch.setattr(opt_module, "_trajectory_cache", temp_cache)


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


def test_status_returns_true_when_cached(client, tmp_path, monkeypatch):
    """Status is active when a trajectory is in the cache (no legacy file needed)."""
    import routers.optimizer as opt_module
    from services.cache.cache_service import CacheService

    cache = CacheService(tmp_path / ".cache/optimizer_seed")
    cache.set("optimise_house", "trajectory", {**SAMPLE_TRAJECTORY, "run_id": "seed.json"})
    monkeypatch.setattr(opt_module, "_trajectory_cache", cache)

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


def test_by_script_served_from_cache_on_second_request(client, traj_dir):
    """Second request is served from cache; deleting the source file has no effect."""
    source = traj_dir / "optimise_house_simulated.json"
    source.write_text(json.dumps(SAMPLE_TRAJECTORY))

    # First request seeds the cache
    resp1 = client.get("/api/optimizer/by-script?script_id=optimise_house")
    assert resp1.status_code == 200

    # Remove the source file
    source.unlink()

    # Second request should still be served from cache
    resp2 = client.get("/api/optimizer/by-script?script_id=optimise_house")
    assert resp2.status_code == 200
    assert "outcomes" in resp2.json()


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
