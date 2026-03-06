"""Tests for real data summary extraction."""

import json
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_input_node_gets_real_data_summary():
    """Input nodes should get real data summaries from execution, not mock data."""
    code = """import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
result = products.skb.eval()
"""

    # Execute and collect events
    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # Find input_summary for the products variable
    input_summary_events = [e for e in events if e.get("type") == "input_summary"]
    assert len(input_summary_events) >= 1, "Should have at least one input_summary event"

    # Get the first input_summary (for products variable)
    products_summary = input_summary_events[0]

    # Verify it has real data structure
    assert "schema" in products_summary
    assert "sample" in products_summary
    assert "row_count" in products_summary

    # Real data should have multiple columns (not just "ID" from mock)
    schema = products_summary["schema"]
    assert len(schema) > 1, f"Real data should have multiple columns, got: {schema}"

    # Check for expected columns from credit_fraud dataset
    column_names = [col["name"] for col in schema]
    # The products table should have columns like basket_ID, item, make, model, etc.
    assert any(col in column_names for col in ["basket_ID", "item", "make", "model"]), \
        f"Should have credit_fraud product columns, got: {column_names}"

    # Sample should have data for these columns
    sample = products_summary["sample"]
    assert len(sample) > 0, "Should have sample rows"
    assert len(sample[0].keys()) > 1, "Sample rows should have multiple columns"


def test_data_summary_is_cached():
    """Data summaries should be cached for reuse across scripts."""
    # Same input in two different scripts
    code1 = """import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
"""

    code2 = """import skrub

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=50, how="random")
"""

    # Execute both
    exec_resp1 = client.post("/api/execute", json={"input_code": code1})
    assert exec_resp1.status_code == 200

    exec_resp2 = client.post("/api/execute", json={"input_code": code2})
    assert exec_resp2.status_code == 200

    # Extract summaries
    def get_input_summary(resp_text):
        events = []
        for line in resp_text.split("\n"):
            if line.strip().startswith("data: "):
                try:
                    events.append(json.loads(line.strip()[6:]))
                except json.JSONDecodeError:
                    pass
        input_summaries = [e for e in events if e.get("type") == "input_summary"]
        return input_summaries[0] if input_summaries else None

    summary1 = get_input_summary(exec_resp1.text)
    summary2 = get_input_summary(exec_resp2.text)

    assert summary1 is not None
    assert summary2 is not None

    # Schemas should be identical (cached from same input)
    assert summary1["schema"] == summary2["schema"], \
        "Cached summaries should have identical schemas"


def test_no_fake_data_on_execution_failure():
    """When real data cannot be obtained, no input_summary events are emitted (no fake/placeholder data)."""
    code = """import skrub

# skrub.var without a default value — no data is available unless env is populated at runtime
products = skrub.var("products")
"""

    # Execute
    exec_resp = client.post("/api/execute", json={"input_code": code})
    assert exec_resp.status_code == 200

    events = []
    for line in exec_resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass

    # No input_summary events should be emitted when data is unavailable.
    # The frontend shows "Run the pipeline to see..." in this case.
    input_summaries = [e for e in events if e.get("type") == "input_summary"]
    assert len(input_summaries) == 0, (
        f"No input_summary events should be emitted when data is unavailable; got: {input_summaries}"
    )


def _collect_events(resp_text):
    events = []
    for line in resp_text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _get_products_input_summary(events):
    for e in events:
        if e.get("type") == "input_summary" and e.get("node_id") and "products" in str(e.get("node_id", "")):
            return e
    # Fallback: first input_summary (many scripts only have one var)
    input_summaries = [e for e in events if e.get("type") == "input_summary"]
    return input_summaries[0] if input_summaries else None


@pytest.mark.parametrize("n", [25, 50, 100])
def test_runner_extract_var_input_summaries_row_count_matches_subsample_size(n):
    """Runner must report row_count that matches the actual subsampled size, not the full dataset.

    When the script has products = skrub.var(...).skb.subsample(n=N), the runner's
    _extract_var_input_summaries materializes the DataOp and reports row_count == N.
    """
    pytest.importorskip("skrub")
    from services.skrub_graph_runner import _extract_var_input_summaries

    script = f"""import skrub
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n={n}, how="random")
"""
    g = {}
    exec(script, g)
    summaries = _extract_var_input_summaries(g)
    products_summary = next((s for s in summaries if s.get("var_name") == "products"), None)
    assert products_summary is not None, f"Expected summary for 'products', got {[s.get('var_name') for s in summaries]}"
    assert products_summary["row_count"] == n, (
        f"row_count must match subsample size n={n}; got {products_summary['row_count']} (full-dataset count would be wrong)"
    )


def test_runner_extract_var_input_summaries_env_subsample_row_count():
    """When env contains a subsampled DataFrame for a var, runner reports that row_count."""
    pytest.importorskip("skrub")
    from services.skrub_graph_runner import _extract_var_input_summaries

    import skrub
    dataset = skrub.datasets.fetch_credit_fraud()
    subsampled = dataset.products.sample(n=50, random_state=42)
    g = {"env": {"products": subsampled}}
    summaries = _extract_var_input_summaries(g)
    products_summary = next((s for s in summaries if s.get("var_name") == "products"), None)
    assert products_summary is not None
    assert products_summary["row_count"] == 50, (
        f"When env['products'] is 50-row sample, row_count must be 50; got {products_summary.get('row_count')}"
    )
