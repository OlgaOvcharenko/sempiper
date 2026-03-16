"""Tests for GetItem to as_X/as_y mapping in skrub-to-compile node mapping."""

from models.schemas import CompileNode, SourceRange
from services.execute_stream import _build_skrub_to_compile_id


def test_getitem_maps_to_as_x():
    """GetItem nodes from skrub should map to as_X nodes in compile graph."""
    # Skrub graph has GetItem node (created by baskets[["ID"]])
    graph = {
        "nodes": [
            {"id": "0", "label": "<Var 'baskets'>"},
            {"id": "1", "label": "<GetItem 'ID'>"},  # This should map to as_X
        ],
        "parents": {},
        "children": {},
    }

    # Compile graph has as_X node
    runnable = [
        CompileNode(
            id="var_baskets_1",
            type="input",
            label="<Var 'baskets'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
        CompileNode(
            id="as_X_2",
            type="input",
            label="as_X",
            source_range=SourceRange(start_line=2, start_column=1, end_line=2, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    # GetItem node should map to as_X compile node
    assert result["1"] == "as_X_2"


def test_getitem_maps_to_as_y():
    """GetItem nodes can map to as_y nodes."""
    graph = {
        "nodes": [
            {"id": "0", "label": "<Var 'baskets'>"},
            {"id": "1", "label": "<GetItem 'fraud_flag'>"},
        ],
        "parents": {},
        "children": {},
    }

    runnable = [
        CompileNode(
            id="var_baskets_1",
            type="input",
            label="<Var 'baskets'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
        CompileNode(
            id="as_y_2",
            type="input",
            label="as_y",
            source_range=SourceRange(start_line=2, start_column=1, end_line=2, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    assert result["1"] == "as_y_2"


def test_multiple_getitems_map_to_as_x_and_as_y():
    """Multiple GetItem nodes should map to as_X and as_y in document order."""
    graph = {
        "nodes": [
            {"id": "0", "label": "<Var 'baskets'>"},
            {"id": "1", "label": "<GetItem 'ID'>"},  # Should map to as_X
            {"id": "2", "label": "<GetItem 'fraud_flag'>"},  # Should map to as_y
        ],
        "parents": {},
        "children": {},
    }

    runnable = [
        CompileNode(
            id="var_baskets_1",
            type="input",
            label="<Var 'baskets'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
        CompileNode(
            id="as_X_2",
            type="input",
            label="as_X",
            source_range=SourceRange(start_line=2, start_column=1, end_line=2, end_column=10),
        ),
        CompileNode(
            id="as_y_3",
            type="input",
            label="as_y",
            source_range=SourceRange(start_line=3, start_column=1, end_line=3, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    # First GetItem maps to as_X, second to as_y
    assert result["1"] == "as_X_2"
    assert result["2"] == "as_y_3"


def test_getitem_without_as_x_as_y_stays_unmapped():
    """GetItem nodes without corresponding as_X/as_y remain unmapped."""
    graph = {
        "nodes": [
            {"id": "0", "label": "<GetItem 'col'>"},  # No as_X or as_y available
        ],
        "parents": {},
        "children": {},
    }

    runnable = [
        CompileNode(
            id="var_df_1",
            type="input",
            label="<Var 'df'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    # GetItem should not be in result (no matching as_X or as_y)
    assert "0" not in result


def test_getitem_mapping_preserves_other_mappings():
    """GetItem mapping doesn't interfere with regular label matching."""
    graph = {
        "nodes": [
            {"id": "0", "label": "<Var 'baskets'>"},
            {"id": "1", "label": "<GetItem 'ID'>"},
            {"id": "2", "label": "sem_fillna"},
        ],
        "parents": {},
        "children": {},
    }

    runnable = [
        CompileNode(
            id="var_baskets_1",
            type="input",
            label="<Var 'baskets'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
        CompileNode(
            id="as_X_2",
            type="input",
            label="as_X",
            source_range=SourceRange(start_line=2, start_column=1, end_line=2, end_column=10),
        ),
        CompileNode(
            id="sem_fillna_3",
            type="operator",
            label="sem_fillna",
            source_range=SourceRange(start_line=3, start_column=1, end_line=3, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    # All nodes should map correctly
    assert result["0"] == "var_baskets_1"
    assert result["1"] == "as_X_2"  # GetItem maps to as_X
    assert result["2"] == "sem_fillna_3"


def test_chained_methods_map_to_groupby():
    """Chained methods like .agg() and .reset_index() after .groupby() map to groupby node."""
    graph = {
        "nodes": [
            {"id": "0", "label": "<Var 'df'>"},
            {"id": "1", "label": "groupby"},
            {"id": "2", "label": "<CallMethod 'agg'>"},
            {"id": "3", "label": "<CallMethod 'reset_index'>"},
        ],
        "parents": {},
        "children": {},
    }

    runnable = [
        CompileNode(
            id="var_df_1",
            type="input",
            label="<Var 'df'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
        CompileNode(
            id="groupby_2",
            type="operator",
            label="groupby",
            source_range=SourceRange(start_line=2, start_column=1, end_line=2, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    # All groupby-related nodes should map to the groupby compile node
    assert result["1"] == "groupby_2"
    assert result["2"] == "groupby_2"  # agg maps to groupby
    assert result["3"] == "groupby_2"  # reset_index maps to groupby


def test_isin_maps_to_compile_counterpart():
    """When a <CallMethod 'isin'> compile node exists, the skrub isin node maps to it."""
    graph = {
        "nodes": [
            {"id": "0", "label": "<Var 'df'>"},
            {"id": "1", "label": "<GetItem 'col'>"},
            {"id": "2", "label": "<CallMethod 'isin'>"},
        ],
        "parents": {},
        "children": {},
    }

    runnable = [
        CompileNode(
            id="var_df_1",
            type="input",
            label="<Var 'df'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
        CompileNode(
            id="isin_2",
            type="operator",
            label="<CallMethod 'isin'>",
            source_range=SourceRange(start_line=2, start_column=1, end_line=2, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    assert result["0"] == "var_df_1"
    assert result["2"] == "isin_2"  # isin maps to its own compile counterpart


def test_isin_without_compile_counterpart_unmapped():
    """When no <CallMethod 'isin'> compile node exists, the skrub isin node is not mapped
    via the special last_mapped_id path (it stays unmapped or gets ancestor mapping)."""
    graph = {
        "nodes": [
            {"id": "0", "label": "<Var 'df'>"},
            {"id": "2", "label": "<CallMethod 'isin'>"},
        ],
        "parents": {},
        "children": {},
    }

    runnable = [
        CompileNode(
            id="var_df_1",
            type="input",
            label="<Var 'df'>",
            source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=10),
        ),
    ]

    result = _build_skrub_to_compile_id(graph, runnable)

    assert result["0"] == "var_df_1"
    # Without a matching compile node and no parent edges, isin is not force-mapped
    assert "2" not in result
