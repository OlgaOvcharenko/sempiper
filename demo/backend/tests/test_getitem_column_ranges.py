"""Tests for GetItem column range matching on lines with .isin() and multiple GetItems.

Covers the line: kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]
and many variations to ensure column ranges are correct and never duplicated.
"""

import pytest

from services.graph_api import (
    _extract_getitem_columns_from_code,
    _find_getitem_position_in_line,
    _merge_source_ranges,
)
from models.schemas import CompileNode, SourceRange


# Exact line from the user's bug report
ISIN_LINE = 'kept_products = products[products["basket_ID"].isin(basket_ids["ID"])]'


class TestFindGetitemPositionInLine:
    """Unit tests for _find_getitem_position_in_line."""

    def test_isin_line_basket_id_position(self):
        """products["basket_ID"] gets correct 1-indexed column range."""
        code = ISIN_LINE + "\n"
        pos = _find_getitem_position_in_line(code, 1, "basket_ID", occurrence=0)
        assert pos is not None
        start, end = pos
        assert start >= 1 and end >= start
        # Extract the span (1-indexed inclusive -> 0-indexed slice)
        line = ISIN_LINE
        snippet = line[start - 1 : end]
        assert "basket_ID" in snippet
        assert snippet.count('"') >= 2

    def test_isin_line_id_position(self):
        """basket_ids["ID"] gets correct 1-indexed column range (not basket_ID)."""
        code = ISIN_LINE + "\n"
        pos = _find_getitem_position_in_line(code, 1, "ID", occurrence=0)
        assert pos is not None
        start, end = pos
        line = ISIN_LINE
        snippet = line[start - 1 : end]
        assert "basket_ids" in snippet or "ID" in snippet
        assert "basket_ID" not in snippet

    def test_isin_line_two_ranges_do_not_overlap(self):
        """basket_ID and ID ranges must not overlap on the isin line."""
        code = ISIN_LINE + "\n"
        pos_basket = _find_getitem_position_in_line(code, 1, "basket_ID", 0)
        pos_id = _find_getitem_position_in_line(code, 1, "ID", 0)
        assert pos_basket is not None and pos_id is not None
        s1, e1 = pos_basket
        s2, e2 = pos_id
        assert e1 < s2 or e2 < s1, "ranges must not overlap"

    def test_end_column_inclusive(self):
        """end_column is inclusive (last character of the GetItem)."""
        code = 'x = df["col"]\n'
        pos = _find_getitem_position_in_line(code, 1, "col", 0)
        assert pos is not None
        start, end = pos
        line = 'x = df["col"]'
        snippet = line[start - 1 : end]
        assert snippet == 'df["col"]', f"expected 'df[\"col\"]', got {snippet!r}"

    def test_same_column_twice_occurrence_0_and_1(self):
        """When same column appears twice, occurrence 0 and 1 return different spans."""
        code = 'a = x["ID"] + y["ID"]\n'
        pos0 = _find_getitem_position_in_line(code, 1, "ID", 0)
        pos1 = _find_getitem_position_in_line(code, 1, "ID", 1)
        assert pos0 is not None and pos1 is not None
        assert pos0 != pos1
        line = 'a = x["ID"] + y["ID"]'
        assert line[pos0[0] - 1 : pos0[1]] == 'x["ID"]'
        assert line[pos1[0] - 1 : pos1[1]] == 'y["ID"]'

    def test_single_quotes(self):
        """Single-quoted column names are found."""
        code = "z = df['col']\n"
        pos = _find_getitem_position_in_line(code, 1, "col", 0)
        assert pos is not None
        line = "z = df['col']"
        assert line[pos[0] - 1 : pos[1]] == "df['col']"

    def test_double_bracket_list_style(self):
        """var[['col']] is matched."""
        code = 'w = df[["col"]]\n'
        pos = _find_getitem_position_in_line(code, 1, "col", 0)
        assert pos is not None
        line = 'w = df[["col"]]'
        assert line[pos[0] - 1 : pos[1]] == 'df[["col"]]'

    def test_occurrence_out_of_range_returns_none(self):
        """When occurrence is beyond matches, return None."""
        code = ISIN_LINE + "\n"
        assert _find_getitem_position_in_line(code, 1, "basket_ID", 1) is None
        assert _find_getitem_position_in_line(code, 1, "ID", 1) is None

    def test_column_not_on_line_returns_none(self):
        """Column that does not appear on the line returns None."""
        code = ISIN_LINE + "\n"
        assert _find_getitem_position_in_line(code, 1, "other_col", 0) is None

    def test_line_number_out_of_range_returns_none(self):
        """Line number 0 or past last line returns None."""
        code = "x = 1\n"
        assert _find_getitem_position_in_line(code, 0, "x", 0) is None
        assert _find_getitem_position_in_line(code, 2, "x", 0) is None

    def test_column_name_with_special_regex_chars(self):
        """Column names that look like regex (e.g. dots) are escaped."""
        code = 'x = df["col.name"]\n'
        pos = _find_getitem_position_in_line(code, 1, "col.name", 0)
        assert pos is not None
        line = 'x = df["col.name"]'
        assert line[pos[0] - 1 : pos[1]] == 'df["col.name"]'

    def test_isin_line_exact_spans(self):
        """On the exact isin line, basket_ID span is before ID span and both are correct."""
        code = ISIN_LINE + "\n"
        line = ISIN_LINE
        pos_basket = _find_getitem_position_in_line(code, 1, "basket_ID", 0)
        pos_id = _find_getitem_position_in_line(code, 1, "ID", 0)
        assert pos_basket is not None and pos_id is not None
        span_basket = line[pos_basket[0] - 1 : pos_basket[1]]
        span_id = line[pos_id[0] - 1 : pos_id[1]]
        assert span_basket == 'products["basket_ID"]', f"got {span_basket!r}"
        assert span_id == 'basket_ids["ID"]', f"got {span_id!r}"
        assert pos_basket[1] < pos_id[0], "basket_ID must end before ID starts"

    def test_three_getitems_same_line_three_occurrences(self):
        """Line with three GetItems for same column (e.g. id) returns three different positions."""
        code = 'out = a["id"] + b["id"] + c["id"]\n'
        for occ in range(3):
            pos = _find_getitem_position_in_line(code, 1, "id", occ)
            assert pos is not None, f"occurrence {occ} should be found"
        assert _find_getitem_position_in_line(code, 1, "id", 3) is None
        # All three spans are different
        positions = [_find_getitem_position_in_line(code, 1, "id", i) for i in range(3)]
        line = code.strip()
        spans = [line[p[0] - 1 : p[1]] for p in positions]
        assert spans == ['a["id"]', 'b["id"]', 'c["id"]']

    def test_nested_brackets_isin_style(self):
        """Nested indexing like outer[inner["col"]] matches inner["col"] for column col."""
        code = 'x = outer[inner["k"]]\n'
        pos = _find_getitem_position_in_line(code, 1, "k", 0)
        assert pos is not None
        line = code.strip()
        assert line[pos[0] - 1 : pos[1]] == 'inner["k"]'


class TestExtractGetitemColumnsFromCode:
    """Unit tests for _extract_getitem_columns_from_code."""

    def test_isin_line_returns_both_columns(self):
        """Line with basket_ID and ID returns both."""
        code = ISIN_LINE + "\n"
        cols = _extract_getitem_columns_from_code(code, 1)
        assert cols == {"basket_ID", "ID"}

    def test_single_getitem(self):
        code = 'x = df["a"]\n'
        assert _extract_getitem_columns_from_code(code, 1) == {"a"}

    def test_multiple_same_column_still_one_in_set(self):
        code = 'a = x["ID"] + y["ID"]\n'
        assert _extract_getitem_columns_from_code(code, 1) == {"ID"}

    def test_line_number_out_of_range_returns_empty(self):
        code = "x = 1\n"
        assert _extract_getitem_columns_from_code(code, 0) == set()
        assert _extract_getitem_columns_from_code(code, 2) == set()


class TestMergeSourceRangesGetitemIsinLine:
    """Merge: GetItem nodes on the isin line get distinct, correct ranges."""

    def test_two_getitem_nodes_same_line_distinct_ranges(self):
        """Two GetItem nodes (basket_ID and ID) on same line get distinct source ranges."""
        script = """import skrub
import sempipes
products = skrub.var("products")
basket_ids = skrub.var("basket_ids")
""" + ISIN_LINE + "\n"
        # Static parse: we may not have a node for the filter line; provide static nodes that
        # don't match so merge uses the final fallback (search all lines for GetItem).
        static_nodes = [
            CompileNode(id="v1", type="input", label="var", source_range=SourceRange(start_line=1, start_column=1, end_line=1, end_column=30)),
            CompileNode(id="v2", type="input", label="var", source_range=SourceRange(start_line=2, start_column=1, end_line=2, end_column=30)),
        ]
        skrub_nodes = [
            CompileNode(id="0", type="input", label="<Var 'products'>", source_range=None),
            CompileNode(id="1", type="operator", label="<Var 'basket_ids'>", source_range=None),
            CompileNode(id="2", type="operator", label='<GetItem \'basket_ID\'>', source_range=None),
            CompileNode(id="3", type="operator", label='<GetItem \'ID\'>', source_range=None),
        ]
        result = _merge_source_ranges(skrub_nodes, static_nodes, script)
        getitems = [n for n in result if n.label.startswith("<GetItem")]
        assert len(getitems) == 2
        ranges = [n.source_range for n in getitems if n.source_range is not None]
        assert len(ranges) == 2, "both GetItems should get a range from fallback"
        r1, r2 = ranges
        assert r1.start_line == r2.start_line == 5  # line of ISIN_LINE in script
        # Ranges must not overlap
        assert (r1.start_column, r1.end_column) != (r2.start_column, r2.end_column)
        assert r1.end_column < r2.start_column or r2.end_column < r1.start_column

    def test_no_duplicate_ranges_assigned(self):
        """No two nodes receive the exact same (start_line, start_col, end_line, end_col)."""
        script = "x = a['id'] + b['id']\n"  # same column 'id' twice
        static_nodes = []
        skrub_nodes = [
            CompileNode(id="0", type="operator", label="<GetItem 'id'>", source_range=None),
            CompileNode(id="1", type="operator", label="<GetItem 'id'>", source_range=None),
        ]
        result = _merge_source_ranges(skrub_nodes, static_nodes, script)
        ranges = [n.source_range for n in result if n.source_range is not None]
        if len(ranges) == 2:
            keys = [(r.start_line, r.start_column, r.end_line, r.end_column) for r in ranges]
            assert keys[0] != keys[1], "two nodes must not get the same range"
