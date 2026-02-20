"""Tests for cache metadata storage and retrieval."""

import json
import pytest
from fastapi.testclient import TestClient
from main import app
from services.cache.cache_service import cache_service
from services.cache.utils import make_cache_key, _normalize_script

client = TestClient(app)


def test_compile_cache_stores_metadata():
    """Test that compile caching stores metadata with script, model, temperature."""
    code = """import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
"""

    llm_name = "gemini/gemini-2.0-flash-exp"
    temperature = 0.7

    # First request - should cache
    resp1 = client.post(
        "/api/compile",
        json={
            "input_code": code,
            "llm_name": llm_name,
            "temperature": temperature,
            "use_cache": True,
        },
    )
    assert resp1.status_code == 200

    # Calculate cache key using the same function as codegen.py
    cache_key = make_cache_key(code, temperature, llm_name)

    # Retrieve metadata
    metadata = cache_service.get_metadata(cache_key, "compile")

    assert metadata is not None, "Metadata should be stored"
    assert metadata["script"] == _normalize_script(code), "Script should match (normalized)"
    assert metadata["llm_name"] == llm_name, "LLM name should match"
    assert metadata["temperature"] == temperature, "Temperature should match"
    assert "use_dynamic" in metadata, "Should include use_dynamic flag"

    print(f"\n✓ Cache metadata stored correctly:")
    print(f"  Cache key: {cache_key}")
    print(f"  LLM: {metadata['llm_name']}")
    print(f"  Temperature: {metadata['temperature']}")
    print(f"  Script length: {len(metadata['script'])} chars")


def test_execute_cache_stores_metadata():
    """Test that execute caching stores metadata with script, model, temperature."""
    code = """import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
result = products.skb.subsample(n=10, how="random")
"""

    llm_name = "gemini/gemini-2.0-flash-exp"
    temperature = 0.5

    # Execute - should cache
    resp = client.post(
        "/api/execute",
        json={
            "input_code": code,
            "llm_name": llm_name,
            "temperature": temperature,
            "use_cache": True,
        },
    )
    assert resp.status_code == 200

    # Calculate cache key using the same function as codegen.py
    cache_key = make_cache_key(code, temperature, llm_name)

    # Retrieve metadata
    metadata = cache_service.get_metadata(cache_key, "execute")

    assert metadata is not None, "Execute metadata should be stored"
    assert metadata["script"] == _normalize_script(code), "Script should match (normalized)"
    assert metadata["llm_name"] == llm_name, "LLM name should match"
    assert metadata["temperature"] == temperature, "Temperature should match"

    print(f"\n✓ Execute cache metadata stored correctly:")
    print(f"  Cache key: {cache_key}")
    print(f"  LLM: {metadata['llm_name']}")
    print(f"  Temperature: {metadata['temperature']}")


def test_cache_metadata_persists_across_retrievals():
    """Test that metadata is stored to disk and can be retrieved after memory clear."""
    code = """import skrub
dataset = skrub.datasets.fetch_credit_fraud()
baskets = skrub.var("baskets", dataset.baskets)
"""

    llm_name = "gemini/gemini-2.0-flash-exp"
    temperature = 1.0

    # Compile and cache
    resp = client.post(
        "/api/compile",
        json={
            "input_code": code,
            "llm_name": llm_name,
            "temperature": temperature,
        },
    )
    assert resp.status_code == 200

    # Calculate cache key using the same function as codegen.py
    cache_key = make_cache_key(code, temperature, llm_name)

    # Clear memory cache (but not file cache)
    cache_service.memory_cache.clear()

    # Metadata should still be retrievable from disk
    metadata = cache_service.get_metadata(cache_key, "compile")

    assert metadata is not None, "Metadata should persist on disk"
    assert metadata["script"] == _normalize_script(code)
    assert metadata["llm_name"] == llm_name
    assert metadata["temperature"] == temperature


def test_cache_delete_removes_metadata():
    """Test that deleting a cache entry also removes its metadata."""
    code = """import skrub
dataset = skrub.datasets.fetch_credit_fraud()
"""

    llm_name = "gemini/gemini-2.0-flash-exp"
    temperature = 0.3

    # Cache compile
    resp = client.post(
        "/api/compile",
        json={
            "input_code": code,
            "llm_name": llm_name,
            "temperature": temperature,
        },
    )
    assert resp.status_code == 200

    # Calculate cache key using the same function as codegen.py
    cache_key = make_cache_key(code, temperature, llm_name)

    # Verify metadata exists
    metadata_before = cache_service.get_metadata(cache_key, "compile")
    assert metadata_before is not None

    # Delete cache entry
    cache_service.delete(cache_key, "compile")

    # Metadata should be gone
    metadata_after = cache_service.get_metadata(cache_key, "compile")
    assert metadata_after is None, "Metadata should be deleted with cache entry"


def test_metadata_includes_script_id():
    """Test that script_id is included in metadata when provided."""
    code = """import skrub
dataset = skrub.datasets.fetch_credit_fraud()
"""

    llm_name = "gemini/gemini-2.0-flash-exp"
    temperature = 0.7
    script_id = "simple"

    # Compile with script_id
    resp = client.post(
        "/api/compile",
        json={
            "input_code": code,
            "llm_name": llm_name,
            "temperature": temperature,
            "script_id": script_id,
        },
    )
    assert resp.status_code == 200

    # Calculate cache key using the same function as codegen.py
    cache_key = make_cache_key(code, temperature, llm_name)

    # Check metadata
    metadata = cache_service.get_metadata(cache_key, "compile")

    assert metadata is not None
    assert metadata["script_id"] == script_id, "Script ID should be in metadata"

    print(f"\n✓ Script ID stored in metadata: {metadata['script_id']}")
