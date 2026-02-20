"""Direct tests for data summary extractor (no FastAPI/mock interference)."""

import tempfile
from pathlib import Path
from services.data_summary_extractor import get_data_summary


def test_data_summary_extractor_direct():
    """Test data summary extractor directly without TestClient."""
    code = """import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        summary = get_data_summary(code, "products", 4, cache_dir=Path(tmpdir))

        # Should have real columns from credit_fraud dataset
        schema = summary["schema"]
        column_names = [col["name"] for col in schema]

        assert len(schema) > 1, f"Should have multiple columns, got: {column_names}"
        assert "basket_ID" in column_names, f"Should have basket_ID column, got: {column_names}"
        assert "item" in column_names, f"Should have item column, got: {column_names}"

        # Should have real row count
        assert summary["row_count"] > 1000, f"Should have many rows, got: {summary['row_count']}"

        # Should have sample data
        assert len(summary["sample"]) > 0, "Should have sample rows"
        assert len(summary["sample"][0]) > 1, "Sample rows should have multiple columns"


def test_data_summary_caching():
    """Data summaries should be cached."""
    code = """import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)

        # First call - should execute and cache
        summary1 = get_data_summary(code, "products", 4, cache_dir=cache_dir)

        # Check cache was created
        cache_files = list((cache_dir / "data_summaries").glob("*.json"))
        assert len(cache_files) == 1, "Should have created cache file"

        # Second call - should use cache
        summary2 = get_data_summary(code, "products", 4, cache_dir=cache_dir)

        # Summaries should be identical
        assert summary1 == summary2, "Cached summaries should match"


def test_data_summary_fallback_on_error():
    """Should fall back to mock data on execution failure."""
    code = """import skrub

# This will fail because undefined_dataset doesn't exist
products = skrub.var("products", undefined_dataset.products)
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        summary = get_data_summary(code, "products", 4, cache_dir=Path(tmpdir))

        # Should still return a summary (fallback)
        assert "schema" in summary
        assert "sample" in summary
        assert "row_count" in summary

        # Will be mock data
        assert len(summary["schema"]) >= 1
