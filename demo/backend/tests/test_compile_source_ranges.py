"""
Tests for compile API source range accuracy.

Source ranges map nodes in the computation graph to their exact positions in the
source code, enabling bidirectional code-graph highlighting:
- Click code → highlight graph node
- Click graph node → highlight code

These tests verify:
1. Line numbers are 1-indexed (first line = 1)
2. Column numbers are 1-indexed (first character = 1)
3. start_column points to the start of the matched pattern
4. end_column points to one past the last character of the pattern (exclusive end)
5. Multi-line constructs are handled correctly
"""

import pytest
from services.compile_parse import extract_nodes_with_ranges, _find_call_ranges


class TestSourceRangeBasics:
    """Basic source range correctness tests."""

    def test_single_line_as_x_source_range(self):
        """as_X on line 1 should have start_line=1, end_line=1."""
        code = "x = sempipes.as_X(df, 'X')"
        nodes, _ = extract_nodes_with_ranges(code)

        assert len(nodes) == 1
        node = nodes[0]
        assert node.label == "as_X"

        r = node.source_range
        assert r is not None
        assert r.start_line == 1
        assert r.end_line == 1
        # as_X( starts at column 14 (0-indexed: 13), +1 for 1-indexed = 14
        # The pattern matches "as_X(" which is 5 chars
        assert r.start_column >= 1
        assert r.end_column > r.start_column

    def test_line_numbering_is_1_indexed(self):
        """First line of code is line 1, not line 0."""
        code = "x = sempipes.as_X(df, 'X')"
        nodes, _ = extract_nodes_with_ranges(code)

        assert nodes[0].source_range.start_line == 1, "Line numbering should be 1-indexed"

    def test_multiline_code_line_numbers(self):
        """Nodes on different lines have correct line numbers."""
        code = """x = sempipes.as_X(df, 'X')
y = x.sem_fillna(target_column='a')
z = y.skb.eval()"""
        nodes, _ = extract_nodes_with_ranges(code)

        # Sort by line number
        nodes_by_line = sorted(nodes, key=lambda n: n.source_range.start_line)

        assert nodes_by_line[0].source_range.start_line == 1  # as_X
        assert nodes_by_line[1].source_range.start_line == 2  # sem_fillna
        assert nodes_by_line[2].source_range.start_line == 3  # skb.eval

    def test_empty_lines_dont_affect_numbering(self):
        """Empty lines are counted but don't confuse line numbering."""
        code = """
x = sempipes.as_X(df, 'X')

y = x.sem_fillna(target_column='a')
"""
        nodes, _ = extract_nodes_with_ranges(code)

        as_x_node = next(n for n in nodes if n.label == "as_X")
        sem_fillna_node = next(n for n in nodes if n.label == "sem_fillna")

        assert as_x_node.source_range.start_line == 2  # Line 1 is empty
        assert sem_fillna_node.source_range.start_line == 4  # Line 3 is empty

    def test_comment_lines_counted(self):
        """Comment lines are counted in line numbers."""
        code = """# Comment line 1
# Comment line 2
x = sempipes.as_X(df, 'X')"""
        nodes, _ = extract_nodes_with_ranges(code)

        assert nodes[0].source_range.start_line == 3


class TestColumnPositions:
    """Tests for column position accuracy."""

    def test_column_position_at_start_of_line(self):
        """Node at start of line has start_column close to 1."""
        code = "sempipes.as_X(df, 'X')"
        nodes, _ = extract_nodes_with_ranges(code)

        # as_X is after "sempipes."
        r = nodes[0].source_range
        # "sempipes." is 9 chars, so as_X starts at column 10
        assert r.start_column == 10

    def test_column_position_with_indentation(self):
        """Indented code has correct column positions."""
        code = "    x = sempipes.as_X(df, 'X')"
        nodes, _ = extract_nodes_with_ranges(code)

        r = nodes[0].source_range
        # 4 spaces + "x = sempipes." = 17 chars, so as_X starts at column 18
        assert r.start_column == 18

    def test_method_call_column_position(self):
        """Method call (.sem_fillna) has correct column position."""
        code = "y = x.sem_fillna(target_column='a')"
        nodes, _ = extract_nodes_with_ranges(code)

        r = nodes[0].source_range
        # "y = x." is 6 chars, so .sem_fillna starts at column 5 (0-indexed)
        # But the pattern matches ".sem_fillna(" so start is at the dot
        assert r.start_column >= 5


class TestSimplePipeline:
    """Tests for the simple.py pipeline script source ranges."""

    SIMPLE_PIPELINE = """import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")

products = products.sem_gen_features(
    nl_prompt="Generate useful features for product analysis.",
    name="product_features",
    how_many=3,
)

result = products.skb.eval()
"""

    def test_simple_pipeline_node_count(self):
        """Simple pipeline should have 4 nodes: var, subsample, sem_gen_features, eval."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)

        labels = [n.label for n in nodes]
        assert any("products" in l for l in labels)  # skrub.var: "products" or "<Var 'products'>"
        assert "skb.subsample" in labels
        assert "sem_gen_features" in labels
        assert "skb.eval" in labels
        assert len(nodes) == 4

    def test_simple_pipeline_var_line(self):
        """skrub.var should be on line 8."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)
        var_node = next(n for n in nodes if (n.label or "") == "products" or (n.label or "").startswith("<Var ") and "products" in (n.label or ""))

        assert var_node.source_range.start_line == 8

    def test_simple_pipeline_subsample_line(self):
        """skb.subsample should be on line 9."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)
        subsample_node = next(n for n in nodes if n.label == "skb.subsample")

        assert subsample_node.source_range.start_line == 9

    def test_simple_pipeline_sem_gen_features_line(self):
        """sem_gen_features should be on line 11 (multi-line call)."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)
        sem_gen_node = next(n for n in nodes if n.label == "sem_gen_features")

        assert sem_gen_node.source_range.start_line == 11

    def test_simple_pipeline_eval_line(self):
        """skb.eval should be on line 17."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)
        eval_node = next(n for n in nodes if n.label == "skb.eval")

        assert eval_node.source_range.start_line == 17

    def test_simple_pipeline_column_positions(self):
        """Verify column positions for simple pipeline nodes."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)

        for node in nodes:
            r = node.source_range
            # Column should be > 0 (1-indexed)
            assert r.start_column >= 1, f"{node.label} has invalid start_column"
            assert r.end_column >= r.start_column, f"{node.label} has end < start"

    def test_simple_pipeline_var_column(self):
        """skrub.var column position should match 'skrub.var(' in the line."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)
        var_node = next(n for n in nodes if (n.label or "") == "products" or (n.label or "").startswith("<Var ") and "products" in (n.label or ""))

        # Line 8: "products = skrub.var("products", dataset.products)"
        # "products = " is 11 chars, "skrub.var(" starts at column 12
        r = var_node.source_range
        assert r.start_column == 12, f"Expected column 12, got {r.start_column}"


class TestMediumPipeline:
    """Tests for medium-complexity pipeline patterns."""

    MEDIUM_SNIPPET = """import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)
baskets = baskets.skb.subsample(n=5000, how="random")

basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Fraud label")

products = products.sem_fillna(
    target_column="item_price",
    how="mean",
)

result = baskets.skb.apply(
    X=basket_ids,
    estimator=fraud_flags,
)
"""

    def test_medium_pipeline_all_nodes_have_ranges(self):
        """All nodes should have source ranges."""
        nodes, _ = extract_nodes_with_ranges(self.MEDIUM_SNIPPET)

        for node in nodes:
            assert node.source_range is not None, f"Node {node.id} missing source_range"
            assert node.source_range.start_line >= 1
            assert node.source_range.start_column >= 1

    def test_medium_pipeline_multiline_calls(self):
        """Multi-line calls should have start_line at the opening."""
        nodes, _ = extract_nodes_with_ranges(self.MEDIUM_SNIPPET)

        # sem_fillna is multi-line starting at line 12
        sem_fillna = next(n for n in nodes if n.label == "sem_fillna")
        assert sem_fillna.source_range.start_line == 12

        # skb.apply is multi-line starting at line 17
        skb_apply = next(n for n in nodes if n.label == "skb.apply")
        assert skb_apply.source_range.start_line == 17


class TestEdgeCases:
    """Edge cases for source range extraction."""

    def test_multiple_nodes_same_line(self):
        """Multiple nodes on same line should have different column positions."""
        # This is unusual but possible with chained calls
        code = "x = sempipes.as_X(df, 'X'); y = sempipes.as_y(df2, 'Y')"
        nodes, _ = extract_nodes_with_ranges(code)

        # Both should be on line 1
        for node in nodes:
            assert node.source_range.start_line == 1

        # But different columns
        if len(nodes) == 2:
            cols = [n.source_range.start_column for n in nodes]
            assert cols[0] != cols[1], "Different nodes same line should have different columns"

    def test_deeply_nested_expression(self):
        """Nested expressions should still be parsed correctly."""
        code = "result = (x.sem_fillna(target_column='a'))"
        nodes, _ = extract_nodes_with_ranges(code)

        assert len(nodes) == 1
        r = nodes[0].source_range
        assert r.start_line == 1
        assert r.start_column >= 1

    def test_code_with_string_containing_pattern(self):
        """Strings containing node patterns should not create false nodes."""
        code = '''x = "sem_fillna"
y = df.sem_fillna(target_column='a')'''
        nodes, _ = extract_nodes_with_ranges(code)

        # Only the actual method call should create a node
        assert len(nodes) == 1
        assert nodes[0].source_range.start_line == 2

    def test_commented_code_not_parsed(self):
        """Commented-out pipeline code should not create nodes."""
        code = """# x = sempipes.as_X(df, 'X')
y = sempipes.as_y(df2, 'Y')"""
        nodes, _ = extract_nodes_with_ranges(code)

        # Only as_y should be found
        assert len(nodes) == 1
        assert nodes[0].label == "as_y"
        assert nodes[0].source_range.start_line == 2


class TestRawEntryParsing:
    """Tests for the low-level _find_call_ranges function."""

    def test_skrub_var_captures_name(self):
        """skrub.var should produce label in skrub format <Var 'name'>."""
        code = 'products = skrub.var("products", data)'
        raw = _find_call_ranges(code)

        assert len(raw) == 1
        assert raw[0].label == "<Var 'products'>"
        assert raw[0].node_type == "input"

    def test_subsample_has_correct_label(self):
        """skb.subsample should have label 'skb.subsample'."""
        code = "products = products.skb.subsample(n=100)"
        raw = _find_call_ranges(code)

        assert len(raw) == 1
        assert raw[0].label == "skb.subsample"
        assert raw[0].node_type == "operator"

    def test_start_end_column_consistency(self):
        """end_column should always be > start_column for non-empty matches."""
        code = """products = skrub.var("products", data)
products = products.skb.subsample(n=100)
products = products.sem_gen_features(nl_prompt="test")
result = products.skb.eval()"""
        raw = _find_call_ranges(code)

        for entry in raw:
            assert entry.end_col > entry.start_col, (
                f"Entry {entry.label} has end_col <= start_col"
            )


class TestSourceRangeAccuracyForHighlighting:
    """
    Tests that verify source ranges work correctly for code highlighting.

    The frontend uses these ranges to highlight code when a graph node is selected.
    Inaccurate ranges cause wrong highlighting or no highlighting.
    """

    def test_highlighting_range_covers_method_name(self):
        """The source range should at minimum cover the method name."""
        code = "y = x.sem_fillna(target_column='a')"
        nodes, _ = extract_nodes_with_ranges(code)

        r = nodes[0].source_range
        line = code.split('\n')[r.start_line - 1]

        # Extract the substring that would be highlighted
        # Note: columns are 1-indexed, Python slicing is 0-indexed
        highlighted = line[r.start_column - 1 : r.end_column - 1]

        # Should contain the method name
        assert "sem_fillna" in highlighted or highlighted.startswith(".sem_fillna")

    def test_highlighting_range_for_skrub_var(self):
        """skrub.var highlighting should cover the pattern."""
        code = 'products = skrub.var("products", data)'
        nodes, _ = extract_nodes_with_ranges(code)

        r = nodes[0].source_range
        line = code
        highlighted = line[r.start_column - 1 : r.end_column - 1]

        # Should match "skrub.var("
        assert "skrub.var" in highlighted

    def test_all_operators_have_meaningful_ranges(self):
        """All operator types should have ranges that match their patterns."""
        operators = [
            ('x.sem_fillna()', "sem_fillna"),
            ('x.sem_gen_features()', "sem_gen_features"),
            ('x.sem_extract_features()', "sem_extract_features"),
            ('x.sem_clean()', "sem_clean"),
            ('x.sem_augment()', "sem_augment"),
            ('x.sem_agg_features()', "sem_agg_features"),
            ('x.sem_refine()', "sem_refine"),
            ('x.sem_select()', "sem_select"),
            ('x.sem_distill()', "sem_distill"),
            ('x.skb.subsample()', "skb.subsample"),
            ('x.skb.apply()', "skb.apply"),
            ('x.skb.eval()', "skb.eval"),
            ('x.skb.apply_with_sem_choose()', "apply_with_sem_choose"),
            ('sem_choose()', "sem_choose"),
        ]

        for code, expected_label in operators:
            nodes, _ = extract_nodes_with_ranges(code)
            if nodes:  # Some patterns might not match alone
                node = nodes[0]
                r = node.source_range
                assert r.start_column >= 1, f"{expected_label} has invalid start_column"
                assert r.end_column > r.start_column, f"{expected_label} has zero-width range"


class TestColumnIndexingConsistency:
    """
    Tests for consistent 1-indexed column positions.

    Monaco editor uses 1-indexed lines and columns. The source ranges must
    be consistently 1-indexed for proper code highlighting.

    For exclusive end ranges (like Monaco):
    - start_column is the 1-indexed position of the first character
    - end_column is the 1-indexed position AFTER the last character

    Example: "sempipes.as_X(" in "sempipes.as_X(df, 'X')"
    - Characters: s(1) e(2) m(3) p(4) i(5) p(6) e(7) s(8) .(9) a(10) s(11) _(12) X(13) ((14)
    - start_column = 10 (the 'a' in 'as_X')
    - end_column = 15 (one past the '(' which is at position 14)
    """

    def test_as_x_exact_column_positions(self):
        """Verify exact column positions for as_X pattern."""
        code = "sempipes.as_X(df, 'X')"
        raw = _find_call_ranges(code)

        assert len(raw) == 1
        entry = raw[0]

        # Pattern "as_X(" matches starting at column 10 (1-indexed)
        # s=1 e=2 m=3 p=4 i=5 p=6 e=7 s=8 .=9 a=10 s=11 _=12 X=13 (=14
        # So as_X( starts at index 9 (0-indexed) = column 10 (1-indexed)
        assert entry.start_col == 10, f"Expected start_col=10, got {entry.start_col}"

        # The pattern "as_X(" is 5 chars: a(10) s(11) _(12) X(13) ((14)
        # End column should be 15 (exclusive, one past the '(')
        assert entry.end_col == 15, f"Expected end_col=15, got {entry.end_col}"

    def test_skrub_var_exact_column_positions(self):
        """Verify exact column positions for skrub.var pattern."""
        code = 'products = skrub.var("products", data)'
        raw = _find_call_ranges(code)

        assert len(raw) == 1
        entry = raw[0]

        # "products = " is 11 chars, "skrub.var(" starts at column 12
        assert entry.start_col == 12, f"Expected start_col=12, got {entry.start_col}"

        # "skrub.var(" is 10 chars, so end should be 12 + 10 = 22
        assert entry.end_col == 22, f"Expected end_col=22, got {entry.end_col}"

    def test_method_call_exact_column_positions(self):
        """Verify exact column positions for method call (.sem_fillna)."""
        code = "y = x.sem_fillna(target_column='a')"
        raw = _find_call_ranges(code)

        assert len(raw) == 1
        entry = raw[0]

        # "y = x" is 5 chars, ".sem_fillna(" starts at column 6
        assert entry.start_col == 6, f"Expected start_col=6, got {entry.start_col}"

        # ".sem_fillna(" is 12 chars, so end should be 6 + 12 = 18
        assert entry.end_col == 18, f"Expected end_col=18, got {entry.end_col}"

    def test_highlighting_extracts_correct_text(self):
        """The highlighted text should match the pattern exactly."""
        code = "sempipes.as_X(df, 'X')"
        raw = _find_call_ranges(code)
        entry = raw[0]

        # Using 1-indexed columns with exclusive end
        highlighted = code[entry.start_col - 1 : entry.end_col - 1]

        # Should extract "as_X("
        assert highlighted == "as_X(", f"Expected 'as_X(', got '{highlighted}'"

    def test_skrub_var_highlighting_extracts_correct_text(self):
        """Verify skrub.var highlighting extracts the correct text."""
        code = 'products = skrub.var("products", data)'
        raw = _find_call_ranges(code)
        entry = raw[0]

        highlighted = code[entry.start_col - 1 : entry.end_col - 1]

        assert highlighted == "skrub.var(", f"Expected 'skrub.var(', got '{highlighted}'"

    def test_sem_fillna_highlighting_extracts_correct_text(self):
        """Verify .sem_fillna highlighting extracts the correct text."""
        code = "y = x.sem_fillna(target_column='a')"
        raw = _find_call_ranges(code)
        entry = raw[0]

        highlighted = code[entry.start_col - 1 : entry.end_col - 1]

        assert highlighted == ".sem_fillna(", f"Expected '.sem_fillna(', got '{highlighted}'"

    def test_skb_subsample_highlighting(self):
        """Verify .skb.subsample highlighting extracts the correct text."""
        code = "products = products.skb.subsample(n=100)"
        raw = _find_call_ranges(code)
        entry = raw[0]

        highlighted = code[entry.start_col - 1 : entry.end_col - 1]

        # Pattern matches ".skb.subsample("
        assert highlighted == ".skb.subsample(", f"Expected '.skb.subsample(', got '{highlighted}'"

    def test_skb_eval_highlighting(self):
        """Verify .skb.eval highlighting extracts the correct text."""
        code = "result = products.skb.eval()"
        raw = _find_call_ranges(code)
        entry = raw[0]

        highlighted = code[entry.start_col - 1 : entry.end_col - 1]

        # Pattern matches ".skb.eval("
        assert highlighted == ".skb.eval(", f"Expected '.skb.eval(', got '{highlighted}'"


class TestSempipesOperatorSourceRanges:
    """Explicit test per sempipes operator: node exists, has source_range, highlighting covers call."""

    def test_sem_fillna_node_and_highlighting(self):
        """sem_fillna: one node, source_range present, highlighted span covers .sem_fillna(."""
        code = "y = x.sem_fillna(target_column='a')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1, "expected one node"
        node = nodes[0]
        assert node.label == "sem_fillna"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_fillna(" in highlighted or highlighted.startswith(".sem_fillna")

    def test_sem_gen_features_node_and_highlighting(self):
        """sem_gen_features: one node, source_range present, highlighted span covers .sem_gen_features(."""
        code = "y = x.sem_gen_features(nl_prompt='gen')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1, "expected one node"
        node = nodes[0]
        assert node.label == "sem_gen_features"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_gen_features(" in highlighted or highlighted.startswith(".sem_gen_features")

    def test_sem_extract_features_node_and_highlighting(self):
        """sem_extract_features: one node, source_range present, highlighted span covers .sem_extract_features(."""
        code = "y = x.sem_extract_features(columns=['a'])"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1, "expected one node"
        node = nodes[0]
        assert node.label == "sem_extract_features"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_extract_features(" in highlighted or highlighted.startswith(".sem_extract_features")

    def test_sem_clean_node_and_highlighting(self):
        """sem_clean: one node, source_range present, highlighted span covers .sem_clean(."""
        code = "y = x.sem_clean(nl_prompt='clean', columns=['a'])"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1
        node = nodes[0]
        assert node.label == "sem_clean"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_clean(" in highlighted or highlighted.startswith(".sem_clean")

    def test_sem_augment_node_and_highlighting(self):
        """sem_augment: one node, source_range present, highlighted span covers .sem_augment(."""
        code = "y = x.sem_augment(nl_prompt='augment')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1
        node = nodes[0]
        assert node.label == "sem_augment"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_augment(" in highlighted or highlighted.startswith(".sem_augment")

    def test_sem_agg_features_node_and_highlighting(self):
        """sem_agg_features: one node, source_range present, highlighted span covers .sem_agg_features(."""
        code = "y = x.sem_agg_features(nl_prompt='agg')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1
        node = nodes[0]
        assert node.label == "sem_agg_features"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_agg_features(" in highlighted or highlighted.startswith(".sem_agg_features")

    def test_sem_refine_node_and_highlighting(self):
        """sem_refine: one node, source_range present, highlighted span covers .sem_refine(."""
        code = "y = x.sem_refine(target_column='a', nl_prompt='refine')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1
        node = nodes[0]
        assert node.label == "sem_refine"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_refine(" in highlighted or highlighted.startswith(".sem_refine")

    def test_sem_select_node_and_highlighting(self):
        """sem_select: one node, source_range present, highlighted span covers .sem_select(."""
        code = "y = x.sem_select(nl_prompt='select')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1
        node = nodes[0]
        assert node.label == "sem_select"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_select(" in highlighted or highlighted.startswith(".sem_select")

    def test_sem_distill_node_and_highlighting(self):
        """sem_distill: one node, source_range present, highlighted span covers .sem_distill(."""
        code = "y = x.sem_distill(nl_prompt='distill')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1
        node = nodes[0]
        assert node.label == "sem_distill"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert ".sem_distill(" in highlighted or highlighted.startswith(".sem_distill")

    def test_sem_choose_node_and_highlighting(self):
        """sem_choose: one node, source_range present, highlighted span covers sem_choose(."""
        code = "choices = sem_choose(name='x')"
        nodes, _ = extract_nodes_with_ranges(code)
        assert len(nodes) == 1, "expected one node"
        node = nodes[0]
        assert node.label == "sem_choose"
        r = node.source_range
        assert r is not None
        line = code.split("\n")[r.start_line - 1]
        highlighted = line[r.start_column - 1 : r.end_column - 1]
        assert "sem_choose(" in highlighted or highlighted.startswith("sem_choose")


class TestMultipleInstancesAndMultiline:
    """Multiple instances of the same operator and multi-line call edge cases."""

    def test_two_sem_extract_features_static_correct_lines(self):
        """Two .sem_extract_features(...) on different lines: two nodes, source_range.start_line matches each call."""
        code = """x = df.sem_extract_features(columns=['a'], nl_prompt='first')
y = x.sem_extract_features(columns=['b'], nl_prompt='second')"""
        nodes, _ = extract_nodes_with_ranges(code)
        sem_extract = [n for n in nodes if n.label == "sem_extract_features"]
        assert len(sem_extract) == 2
        by_line = sorted(sem_extract, key=lambda n: n.source_range.start_line)
        assert by_line[0].source_range.start_line == 1
        assert by_line[1].source_range.start_line == 2

    def test_two_sem_gen_features_static_correct_lines(self):
        """Two .sem_gen_features(...) on different lines: two nodes, source_range.start_line matches each call."""
        code = """x = df.sem_gen_features(nl_prompt='first')
y = x.sem_gen_features(nl_prompt='second')"""
        nodes, _ = extract_nodes_with_ranges(code)
        sem_gen = [n for n in nodes if n.label == "sem_gen_features"]
        assert len(sem_gen) == 2
        by_line = sorted(sem_gen, key=lambda n: n.source_range.start_line)
        assert by_line[0].source_range.start_line == 1
        assert by_line[1].source_range.start_line == 2

    def test_sem_extract_features_multiline_user_style(self):
        """sem_extract_features multi-line (opening paren on one line, args below): start_line is line of .sem_extract_features(."""
        code = """unique_brands = products[["make"]].drop_duplicates()
brand_risk_info = unique_brands.sem_extract_features(
    nl_prompt="Extract features from make.",
    name="brand_risk_features",
    input_columns=["make"],
    generate_via_code=True,
)"""
        nodes, _ = extract_nodes_with_ranges(code)
        sem_extract = [n for n in nodes if n.label == "sem_extract_features"]
        assert len(sem_extract) == 1
        assert sem_extract[0].source_range.start_line == 2, "start_line should be the line with .sem_extract_features("


class TestNodeToLineMapping:
    """
    Tests for verifying correct node-to-line association.

    These tests ensure that clicking a graph node highlights the correct code line,
    not the line before or a different node with the same label.
    """

    def test_each_node_has_unique_start_line(self):
        """Each node in a well-formed pipeline should be on a distinct line."""
        code = """products = skrub.var("products", data)
products = products.skb.subsample(n=100)
products = products.sem_gen_features(nl_prompt="test")
result = products.skb.eval()"""
        nodes, _ = extract_nodes_with_ranges(code)

        # Each node should be on a different line
        lines_used: dict[int, str] = {}
        for node in nodes:
            line = node.source_range.start_line
            assert line not in lines_used, (
                f"Line {line} used by both {lines_used[line]} and {node.id}"
            )
            lines_used[line] = node.id

    def test_nodes_sorted_by_line_match_document_order(self):
        """Nodes sorted by start_line should match document order."""
        code = """products = skrub.var("products", data)
products = products.skb.subsample(n=100)
products = products.sem_gen_features(nl_prompt="test")
result = products.skb.eval()"""
        nodes, _ = extract_nodes_with_ranges(code)

        # Sort by start_line
        sorted_nodes = sorted(nodes, key=lambda n: n.source_range.start_line)

        # Should be: var, subsample, sem_gen_features, eval (var in skrub format <Var 'name'>)
        expected_labels = ["<Var 'products'>", "skb.subsample", "sem_gen_features", "skb.eval"]
        actual_labels = [n.label for n in sorted_nodes]
        assert actual_labels == expected_labels

    def test_consecutive_nodes_have_consecutive_lines(self):
        """Adjacent nodes should have start_lines that reflect their code order."""
        code = """line1 = skrub.var("line1", data)
line2 = line1.sem_fillna(target_column='a')
line3 = line2.sem_gen_features(nl_prompt="test")"""
        nodes, _ = extract_nodes_with_ranges(code)

        sorted_nodes = sorted(nodes, key=lambda n: n.source_range.start_line)

        # Verify line numbers are increasing
        prev_line = 0
        for node in sorted_nodes:
            assert node.source_range.start_line > prev_line, (
                f"Node {node.id} (line {node.source_range.start_line}) should be after line {prev_line}"
            )
            prev_line = node.source_range.start_line

    def test_node_line_does_not_match_previous_operator(self):
        """
        Regression test: clicking node N should NOT highlight node N-1's line.

        This is the specific bug: clicking sem_gen_features highlights the line
        where sem_fillna is defined, not where sem_gen_features is defined.
        """
        code = """x = skrub.var("x", data)
x = x.sem_fillna(target_column='a')
x = x.sem_gen_features(nl_prompt="test")
result = x.skb.eval()"""
        nodes, _ = extract_nodes_with_ranges(code)

        # Find nodes by label
        fillna = next(n for n in nodes if n.label == "sem_fillna")
        gen_features = next(n for n in nodes if n.label == "sem_gen_features")

        # sem_gen_features should NOT have the same start_line as sem_fillna
        assert gen_features.source_range.start_line != fillna.source_range.start_line, (
            f"sem_gen_features (line {gen_features.source_range.start_line}) should not "
            f"have the same line as sem_fillna (line {fillna.source_range.start_line})"
        )

        # Verify the actual lines
        assert fillna.source_range.start_line == 2
        assert gen_features.source_range.start_line == 3

    def test_highlighting_text_matches_operator_name(self):
        """The text at each source range should contain the operator pattern."""
        code = """x = skrub.var("x", data)
x = x.sem_fillna(target_column='a')
x = x.sem_gen_features(nl_prompt="test")
result = x.skb.eval()"""
        nodes, _ = extract_nodes_with_ranges(code)
        lines = code.split('\n')

        for node in nodes:
            r = node.source_range
            line = lines[r.start_line - 1]
            highlighted = line[r.start_column - 1 : r.end_column - 1]

            # The highlighted text should match the expected pattern
            if node.label == "x":
                assert "skrub.var" in highlighted
            elif node.label == "sem_fillna":
                assert "sem_fillna" in highlighted
            elif node.label == "sem_gen_features":
                assert "sem_gen_features" in highlighted
            elif node.label == "skb.eval":
                assert "skb.eval" in highlighted


class TestActualPipelineFiles:
    """Tests using actual pipeline script content."""

    SIMPLE_PIPELINE = """import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

import skrub
import sempipes

dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")

products = products.sem_gen_features(
    nl_prompt="Generate useful features for product analysis.",
    name="product_features",
    how_many=3,
)

result = products.skb.eval()
"""

    def test_simple_pipeline_nodes_match_expected_lines(self):
        """Each node in simple.py should be on its expected line."""
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)

        # Expected line numbers for simple.py
        # Line 8: skrub.var
        # Line 9: skb.subsample
        # Line 11: sem_gen_features (multi-line)
        # Line 17: skb.eval

        var_node = next(n for n in nodes if (n.label or "") == "products" or (n.label or "").startswith("<Var ") and "products" in (n.label or ""))
        subsample_node = next(n for n in nodes if n.label == "skb.subsample")
        gen_features_node = next(n for n in nodes if n.label == "sem_gen_features")
        eval_node = next(n for n in nodes if n.label == "skb.eval")

        assert var_node.source_range.start_line == 8, f"var should be on line 8, got {var_node.source_range.start_line}"
        assert subsample_node.source_range.start_line == 9, f"subsample should be on line 9, got {subsample_node.source_range.start_line}"
        assert gen_features_node.source_range.start_line == 11, f"sem_gen_features should be on line 11, got {gen_features_node.source_range.start_line}"
        assert eval_node.source_range.start_line == 17, f"eval should be on line 17, got {eval_node.source_range.start_line}"

    def test_simple_pipeline_no_node_has_previous_nodes_line(self):
        """
        Regression test: no node should have the same start_line as the previous node.

        This specifically tests the bug where clicking sem_gen_features highlights
        the subsample line instead.
        """
        nodes, _ = extract_nodes_with_ranges(self.SIMPLE_PIPELINE)
        sorted_nodes = sorted(nodes, key=lambda n: n.source_range.start_line)

        for i in range(1, len(sorted_nodes)):
            prev_node = sorted_nodes[i - 1]
            curr_node = sorted_nodes[i]
            assert curr_node.source_range.start_line > prev_node.source_range.start_line, (
                f"Node {curr_node.id} (line {curr_node.source_range.start_line}) should be "
                f"AFTER {prev_node.id} (line {prev_node.source_range.start_line}), not equal"
            )
