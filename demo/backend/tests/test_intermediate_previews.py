"""Tests for intermediate node output previews (NODE_PREVIEW, VAR_PREVIEW, get_var_producer)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.compile_parse import extract_nodes_with_ranges, get_var_producer
from services.execute_stream import (
    _build_static_to_dynamic_id,
    _parse_var_previews_from_stdout,
)


def test_get_var_producer_returns_var_to_node_mapping():
    """get_var_producer maps variable names to the node_id that produces them."""
    code = """
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=50)
x = sempipes.as_X(products[["id"]])
result = products.skb.eval()
"""
    vp = get_var_producer(code)
    assert isinstance(vp, dict)
    # Should have at least one assignment that produces a var
    assert "products" in vp or "x" in vp or "result" in vp
    for var_name, node_id in vp.items():
        assert isinstance(var_name, str) and isinstance(node_id, str)
        assert len(node_id) > 0


def test_get_var_producer_empty_code_returns_empty():
    """get_var_producer on code with no pipeline calls returns empty dict."""
    vp = get_var_producer("x = 1\ny = 2")
    assert vp == {}


def test_parse_var_previews_from_stdout():
    """_parse_var_previews_from_stdout extracts ##VAR_PREVIEW## blocks."""
    stdout = """
##VAR_PREVIEW##
{"var_name": "products", "schema": [{"name": "id", "dtype": "int64"}], "sample": [{"id": 1}], "row_count": 10}
##END##
##VAR_PREVIEW##
{"var_name": "result", "schema": [{"name": "a", "dtype": "object"}], "sample": [], "row_count": 0}
##END##
"""
    previews = _parse_var_previews_from_stdout(stdout)
    assert len(previews) == 2
    assert previews[0]["var_name"] == "products"
    assert previews[0]["schema"][0]["name"] == "id"
    assert previews[0]["row_count"] == 10
    assert previews[1]["var_name"] == "result"
    assert previews[1]["row_count"] == 0


def test_parse_var_previews_from_stdout_empty():
    """_parse_var_previews_from_stdout with no blocks returns empty list."""
    assert _parse_var_previews_from_stdout("") == []
    assert _parse_var_previews_from_stdout("##NODE_PREVIEW##\n{}\n##END##") == []


def test_build_static_to_dynamic_id_maps_by_label_and_order():
    """_build_static_to_dynamic_id maps static node IDs to dynamic by (label, index)."""
    from models.schemas import CompileNode, SourceRange

    static_nodes = [
        CompileNode(id="var_products_4", type="input", label="<Var 'products'>", source_range=SourceRange(start_line=4, start_column=1, end_line=4, end_column=20)),
        CompileNode(id="subsample_5", type="operator", label="skb.subsample", source_range=SourceRange(start_line=5, start_column=1, end_line=5, end_column=30)),
    ]
    runnable = [
        CompileNode(id="0", type="input", label="<Var 'products'>", source_range=None),
        CompileNode(id="1", type="operator", label="skb.subsample", source_range=None),
    ]
    mapping = _build_static_to_dynamic_id(static_nodes, runnable)
    assert mapping.get("var_products_4") == "0"
    assert mapping.get("subsample_5") == "1"


def test_build_static_to_dynamic_id_empty_inputs():
    """_build_static_to_dynamic_id with empty lists returns empty dict."""
    assert _build_static_to_dynamic_id([], []) == {}
    from models.schemas import CompileNode
    assert _build_static_to_dynamic_id([CompileNode(id="a", type="input", label="x", source_range=None)], []) == {}
    assert _build_static_to_dynamic_id([], [CompileNode(id="0", type="input", label="x", source_range=None)]) == {}


def test_execute_stream_emits_node_data_when_mock_stdout_has_node_preview(monkeypatch):
    """When mock runner stdout includes NODE_PREVIEW, stream emits node_data with schema/sample/row_count."""
    from unittest.mock import MagicMock
    import subprocess
    from fastapi.testclient import TestClient
    from main import app

    _real_popen = subprocess.Popen

    def _fake_popen(*args, **kwargs):
        cmd = args[0] if args else []
        if not (isinstance(cmd, list) and len(cmd) >= 3 and "skrub_graph_runner" in " ".join(cmd)):
            return _real_popen(*args, **kwargs)
        proc = MagicMock()
        proc.stdin = MagicMock()
        lines = [
            b"##SEMPIPES_NODE_CODE##\n",
            (json.dumps({"index": 0, "code": "pass", "skrub_node_id": "0"}) + "\n").encode("utf-8"),
            b"##END##\n",
            b"##SKRUB_GRAPH##\n",
            (json.dumps({
                "nodes": [{"id": "0", "label": "var_products", "is_sempipes_semantic": False}],
                "parents": {"0": []},
                "children": {"0": []},
                "sempipesNodeIds": [],
            }) + "\n").encode("utf-8"),
            b"##END##\n",
            b"##NODE_PREVIEW##\n",
            (json.dumps({"node_id": "0", "schema": [{"name": "id", "dtype": "int64"}], "sample": [{"id": 1}], "row_count": 5}) + "\n").encode("utf-8"),
            b"##END##\n",
            b"##EXECUTION_STATS##\n",
            b'{"duration_ms": 100, "cost_usd": 0}\n',
            b"##END##\n",
            b"",
        ]
        proc.stdout.readline.side_effect = lines
        proc.wait.return_value = 0
        proc.returncode = 0
        proc.pid = 12345
        return proc

    monkeypatch.setattr("services.execute_stream.subprocess.Popen", _fake_popen)
    client = TestClient(app)
    code = "products = skrub.var('products', dataset.products)\nresult = products.skb.eval()"
    resp = client.post("/api/execute", json={"input_code": code})
    assert resp.status_code == 200
    events = []
    for line in resp.text.split("\n"):
        if line.strip().startswith("data: "):
            try:
                events.append(json.loads(line.strip()[6:]))
            except json.JSONDecodeError:
                pass
    node_data_events = [e for e in events if e.get("type") == "node_data"]
    assert len(node_data_events) >= 1
    one = node_data_events[0]
    assert "schema" in one and "sample" in one and "row_count" in one
    assert len(one["schema"]) >= 1 and one["row_count"] >= 0


# ---------------------------------------------------------------------------
# Tests for _to_dataframe and _extract_preview_from_dataop (Series / placeholder)
# ---------------------------------------------------------------------------

import pandas as pd
import numpy as np
from types import SimpleNamespace
from services.skrub_graph_runner import _to_dataframe, _extract_preview_from_dataop


def test_to_dataframe_returns_dataframe_as_is():
    df = pd.DataFrame({"a": [1, 2]})
    assert _to_dataframe(df) is df


def test_to_dataframe_converts_series():
    s = pd.Series([10, 20, 30], name="col")
    result = _to_dataframe(s)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 3


def test_to_dataframe_converts_ndarray():
    arr = np.array([[1, 2], [3, 4]])
    result = _to_dataframe(arr)
    assert isinstance(result, pd.DataFrame)
    assert result.shape == (2, 2)


def test_to_dataframe_returns_none_for_string():
    assert _to_dataframe("preview") is None


def test_to_dataframe_returns_none_for_int():
    assert _to_dataframe(42) is None


def test_extract_preview_handles_series():
    """When skb.preview() returns a Series, _extract_preview_from_dataop returns a proper preview dict."""
    series = pd.Series([1, 2, 3], name="ID")
    skb = SimpleNamespace(preview=lambda: series, eval=lambda: None)
    node_obj = SimpleNamespace(skb=skb)

    result = _extract_preview_from_dataop(node_obj, "7")
    assert result is not None
    assert result["node_id"] == "7"
    assert result["row_count"] == 3
    assert len(result["schema"]) >= 1
    assert any(c["name"] == "ID" for c in result["schema"])


def test_extract_preview_skips_placeholder():
    """When preview() returns a non-tabular placeholder and eval fails, return None (not a fake row)."""
    skb = SimpleNamespace(
        preview=lambda: "preview",
        eval=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no data")),
    )
    node_obj = SimpleNamespace(skb=skb)

    result = _extract_preview_from_dataop(node_obj, "5")
    assert result is None, "should not emit placeholder row like {'value': 'preview'}"


def test_extract_preview_prefers_eval_env_over_placeholder():
    """When preview() returns a placeholder but eval(env) returns a DataFrame, use the DataFrame."""
    df = pd.DataFrame({"x": [10, 20], "y": [30, 40]})
    skb = SimpleNamespace(
        preview=lambda: "preview",
        eval=lambda env: df,
    )
    node_obj = SimpleNamespace(skb=skb)

    result = _extract_preview_from_dataop(node_obj, "9", env={"baskets": df})
    assert result is not None
    assert result["node_id"] == "9"
    assert result["row_count"] == 2
    assert len(result["schema"]) == 2


def test_extract_preview_returns_none_when_no_skb():
    """Node without .skb attribute yields None."""
    node_obj = SimpleNamespace()
    assert _extract_preview_from_dataop(node_obj, "0") is None
