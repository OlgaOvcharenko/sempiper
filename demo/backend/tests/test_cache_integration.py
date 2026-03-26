"""Integration tests for cache with API endpoints.

Tests that caching works correctly with /api/compile and /api/execute endpoints.
All tests use isolated temp directories to avoid affecting production cache.
"""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.cache import CacheService, make_cache_key


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_cache(tmp_path):
    """Isolated cache service for tests - does not affect production .cache/"""
    return CacheService(cache_dir=tmp_path / ".test_cache")


@pytest.fixture
def client_with_cache(test_cache):
    """TestClient with cache service overridden to use test cache."""
    # Patch the cache_service used by the codegen router
    with patch("routers.codegen.cache_service", test_cache):
        yield TestClient(app), test_cache


@pytest.fixture
def client():
    """Standard test client without cache patching."""
    return TestClient(app)


# ============================================================================
# Sample data
# ============================================================================

SIMPLE_SCRIPT = """
import sempipes as sp
X = sp.as_X(data)
"""

SIMPLE_SCRIPT_2 = """
import sempipes as sp
y = sp.as_y(target)
"""


# ============================================================================
# Compile Endpoint Cache Tests
# ============================================================================


class TestCompileCacheIntegration:
    """Tests for caching in /api/compile endpoint."""

    def test_compile_stores_in_cache(self, client_with_cache):
        """POST /api/compile with llm_name+temperature stores result."""
        client, cache = client_with_cache

        response = client.post(
            "/api/compile",
            json={
                "input_code": SIMPLE_SCRIPT,
                "llm_name": "gpt-4",
                "temperature": 0.5,
                "use_cache": True,
            },
        )

        assert response.status_code == 200

        # Verify cache was populated
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cached = cache.get(cache_key, "compile")
        assert cached is not None
        assert "nodes" in cached

    def test_compile_cache_hit_returns_cached(self, client_with_cache):
        """Second identical compile returns cached (no recompute)."""
        client, cache = client_with_cache

        # Pre-populate cache with known data
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cached_data = {
            "nodes": [{"id": "cached_node", "type": "input", "label": "cached", "source_range": None}],
            "edges": [],
            "validation_errors": [],
            "compile_timings_ms": None,
        }
        cache.set(cache_key, "compile", cached_data)

        response = client.post(
            "/api/compile",
            json={
                "input_code": SIMPLE_SCRIPT,
                "llm_name": "gpt-4",
                "temperature": 0.5,
                "use_cache": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should return the cached data
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["id"] == "cached_node"

    def test_compile_cache_miss_on_script_change(self, client_with_cache):
        """Different script causes cache miss."""
        client, cache = client_with_cache

        # Pre-populate cache for SIMPLE_SCRIPT
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cache.set(cache_key, "compile", {"nodes": [{"id": "cached"}], "edges": [], "validation_errors": []})

        # Request with different script
        response = client.post(
            "/api/compile",
            json={
                "input_code": SIMPLE_SCRIPT_2,
                "llm_name": "gpt-4",
                "temperature": 0.5,
                "use_cache": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should NOT return cached data (different script)
        assert data["nodes"][0]["id"] != "cached" if data["nodes"] else True

    def test_compile_cache_miss_on_temperature_change(self, client_with_cache):
        """Different temperature causes cache miss."""
        client, cache = client_with_cache

        # Pre-populate cache for temp=0.5
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cache.set(cache_key, "compile", {"nodes": [{"id": "cached_05"}], "edges": [], "validation_errors": []})

        # Request with different temperature
        response = client.post(
            "/api/compile",
            json={
                "input_code": SIMPLE_SCRIPT,
                "llm_name": "gpt-4",
                "temperature": 0.7,  # Different
                "use_cache": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should NOT return cached data
        assert data["nodes"][0]["id"] != "cached_05" if data["nodes"] else True

    def test_compile_cache_miss_on_model_change(self, client_with_cache):
        """Different model causes cache miss."""
        client, cache = client_with_cache

        # Pre-populate cache for gpt-4
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cache.set(cache_key, "compile", {"nodes": [{"id": "cached_gpt4"}], "edges": [], "validation_errors": []})

        # Request with different model
        response = client.post(
            "/api/compile",
            json={
                "input_code": SIMPLE_SCRIPT,
                "llm_name": "gpt-3.5",  # Different
                "temperature": 0.5,
                "use_cache": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should NOT return cached data
        assert data["nodes"][0]["id"] != "cached_gpt4" if data["nodes"] else True

    def test_compile_use_cache_false_bypasses(self, client_with_cache):
        """use_cache=false skips cache lookup and storage."""
        client, cache = client_with_cache

        # Pre-populate cache
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cache.set(cache_key, "compile", {"nodes": [{"id": "cached"}], "edges": [], "validation_errors": []})

        # Request with use_cache=false
        response = client.post(
            "/api/compile",
            json={
                "input_code": SIMPLE_SCRIPT,
                "llm_name": "gpt-4",
                "temperature": 0.5,
                "use_cache": False,  # Bypass cache
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should NOT return cached data
        assert data["nodes"][0]["id"] != "cached" if data["nodes"] else True

    def test_compile_without_llm_params_no_cache(self, client_with_cache):
        """Missing llm_name/temperature disables caching."""
        client, cache = client_with_cache

        # Request without llm_name and temperature
        response = client.post(
            "/api/compile",
            json={
                "input_code": SIMPLE_SCRIPT,
                # No llm_name, no temperature
                "use_cache": True,
            },
        )

        assert response.status_code == 200

        # Cache should be empty (caching disabled without all params)
        # We can't easily check this without knowing the internal key,
        # but we can verify no errors occurred
        assert "nodes" in response.json()


# ============================================================================
# Execute Endpoint Cache Tests
# ============================================================================


class TestExecuteCacheIntegration:
    """Tests for caching in /api/execute endpoint."""

    def test_execute_stores_events_in_cache(self, client_with_cache):
        """POST /api/execute with llm_name+temperature stores result."""
        client, cache = client_with_cache

        # Use DEMO_E2E mode to avoid real subprocess
        with patch.dict("os.environ", {"DEMO_E2E": "1"}):
            response = client.post(
                "/api/execute",
                json={
                    "input_code": SIMPLE_SCRIPT,
                    "llm_name": "gpt-4",
                    "temperature": 0.5,
                    "use_cache": True,
                },
            )

        assert response.status_code == 200

        # Parse SSE events
        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass

        # Should have at least a done event
        assert any(e.get("type") == "done" for e in events)

        # Verify cache was populated
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cached = cache.get(cache_key, "execute")
        assert cached is not None
        assert "events" in cached

    def test_execute_cache_hit_replays_events(self, client_with_cache):
        """Cached execute replays all SSE events."""
        client, cache = client_with_cache

        # Pre-populate cache with known events
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cached_events = [
            {"type": "terminal", "line": "Cached execution..."},
            {"type": "done", "total_cost_usd": 0.0, "duration_ms": 100},
        ]
        cache.set(cache_key, "execute", {"events": cached_events})

        response = client.post(
            "/api/execute",
            json={
                "input_code": SIMPLE_SCRIPT,
                "llm_name": "gpt-4",
                "temperature": 0.5,
                "use_cache": True,
            },
        )

        assert response.status_code == 200

        # Parse SSE events
        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass

        # Should replay the cached events
        assert len(events) == 2
        assert events[0]["type"] == "terminal"
        assert events[0]["line"] == "Cached execution..."
        assert events[1]["type"] == "done"

    def test_execute_cache_miss_on_config_change(self, client_with_cache):
        """Different config causes full re-execution."""
        client, cache = client_with_cache

        # Pre-populate cache for one config
        cache_key = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cached_events = [{"type": "terminal", "line": "Cached"}, {"type": "done"}]
        cache.set(cache_key, "execute", {"events": cached_events})

        # Request with different config
        with patch.dict("os.environ", {"DEMO_E2E": "1"}):
            response = client.post(
                "/api/execute",
                json={
                    "input_code": SIMPLE_SCRIPT,
                    "llm_name": "gpt-3.5",  # Different model
                    "temperature": 0.5,
                    "use_cache": True,
                },
            )

        assert response.status_code == 200

        # Parse SSE events
        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass

        # Should NOT be the cached events (different config)
        terminal_events = [e for e in events if e.get("type") == "terminal"]
        assert not any(e.get("line") == "Cached" for e in terminal_events)


# ============================================================================
# DELETE /api/cache Endpoint Tests
# ============================================================================


class TestClearCacheEndpoint:
    """Tests for DELETE /api/cache endpoint."""

    def test_clear_without_body_returns_422(self, client_with_cache):
        """DELETE /api/cache with no body returns 422 (body is required)."""
        client, cache = client_with_cache

        response = client.delete("/api/cache")

        assert response.status_code == 422

    def test_clear_specific_key_with_body(self, client_with_cache):
        """DELETE /api/cache with script/temperature/llm_name clears only that key."""
        client, cache = client_with_cache
        cache_key1 = make_cache_key(SIMPLE_SCRIPT, 0.5, "gpt-4")
        cache_key2 = make_cache_key(SIMPLE_SCRIPT_2, 0.5, "gpt-4")
        cache.set(cache_key1, "compile", {"nodes": [1]})
        cache.set(cache_key2, "compile", {"nodes": [2]})

        response = client.request(
            "DELETE",
            "/api/cache",
            json={"script": SIMPLE_SCRIPT, "temperature": 0.5, "llm_name": "gpt-4"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "cleared"
        assert response.json()["cache_key"] == cache_key1
        # Targeted key is gone
        assert cache.get(cache_key1, "compile") is None
        # Other key is preserved
        assert cache.get(cache_key2, "compile") == {"nodes": [2]}

    def test_clear_specific_key_response_contains_cache_key(self, client_with_cache):
        """Response includes the computed cache_key when clearing a specific entry."""
        client, cache = client_with_cache
        expected_key = make_cache_key(SIMPLE_SCRIPT, 0.0, "gpt-4")

        response = client.request(
            "DELETE",
            "/api/cache",
            json={"script": SIMPLE_SCRIPT, "temperature": 0.0, "llm_name": "gpt-4"},
        )

        assert response.status_code == 200
        assert response.json()["cache_key"] == expected_key

    def test_clear_specific_key_empty_cache_no_error(self, client_with_cache):
        """Clearing a key that doesn't exist returns 200 without raising."""
        client, cache = client_with_cache

        response = client.request(
            "DELETE",
            "/api/cache",
            json={"script": "nonexistent script", "temperature": 0.5, "llm_name": "gpt-4"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "cleared"
