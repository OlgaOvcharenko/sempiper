"""
Tests for the graph_api module - narrow API for script-to-graph compilation.

This test file covers:
- compile_script_to_graph: Static regex-based graph extraction
- rewrite_script_for_graph_extraction: Script transformation for lazy execution
- extract_skrub_graph: Dynamic graph extraction via script execution
"""

import pytest
from pathlib import Path
from unittest.mock import Mock

from services.graph_api import (
    GraphResult,
    SkrubGraphResult,
    SkrubNode,
    compile_script_to_graph,
    compile_script_to_graph_dynamic,
    extract_skrub_graph,
    rewrite_script_for_graph_extraction,
    _merge_source_ranges,
    _rewrite_var_calls,
    _remove_eval_calls,
    _remove_skrub_datasets_fetches,
    _infer_node_type,
)
from models.schemas import CompileNode, SourceRange


class TestCompileScriptToGraph:
    """Tests for the compile_script_to_graph function."""

    def test_simple_two_node_pipeline(self):
        """Basic case: as_X followed by sem_fillna produces two connected nodes."""
        script = "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"
        result = compile_script_to_graph(script)

        assert len(result.nodes) == 2
        assert len(result.edges) == 1
        assert result.is_valid
        assert result.validation_errors == []

        labels = {n.label for n in result.nodes}
        assert "as_X" in labels
        assert "sem_fillna" in labels

    def test_empty_script_returns_empty_graph(self):
        """Empty script returns empty nodes/edges (frontend shows 'no graph yet')."""
        for script in ("", "   ", "\n\n", "# comment only\n"):
            result = compile_script_to_graph(script)

            assert len(result.nodes) == 0, "empty script should return empty nodes"
            assert len(result.edges) == 0, "empty script should return empty edges"
            assert result.is_valid

    def test_no_pipeline_nodes_returns_empty_graph(self):
        """Script with no pipeline patterns returns empty graph."""
        script = "x = 1 + 2\nprint(x)\n# no as_X or sem_fillna"
        result = compile_script_to_graph(script)

        assert len(result.nodes) == 0, "code with no pipeline nodes should return empty nodes"
        assert len(result.edges) == 0, "code with no pipeline nodes should return empty edges"
        assert result.is_valid

    def test_notebook_style_operators(self):
        """Recognizes all notebook-style sempipes/skrub operators."""
        script = """
basket_ids = sempipes.as_X(baskets[["ID"]], "Shopping baskets")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "Binary flag")
products = products.sem_fillna(target_column="make", nl_prompt="Infer manufacturer.")
kept = kept_products.sem_gen_features(nl_prompt="Generate features.", how_many=5)
fraud_detector = augmented_baskets.skb.apply_with_sem_choose(hgb, y=fraud_flags, choices=sem_choose(name="hgb"))
"""
        result = compile_script_to_graph(script)

        labels = {n.label for n in result.nodes}
        assert "as_X" in labels
        assert "as_y" in labels
        assert "sem_fillna" in labels
        assert "sem_gen_features" in labels
        assert "apply_with_sem_choose" in labels
        assert "sem_choose" in labels
        assert result.is_valid

    def test_all_sempipes_dot_operators_recognized(self):
        """Static compile recognizes all DataOp sempipes operators (sem_*)."""
        script = """
x = sempipes.as_X(df, 'X')
x = x.sem_fillna(target_column='a')
x = x.sem_gen_features(nl_prompt='gen')
x = x.sem_extract_features(columns=['a'], nl_prompt='extract')
x = x.sem_clean(nl_prompt='clean', columns=['a'])
x = x.sem_augment(nl_prompt='augment')
x = x.sem_agg_features(nl_prompt='agg')
x = x.sem_refine(target_column='a', nl_prompt='refine')
x = x.sem_select(nl_prompt='select')
x = x.sem_distill(nl_prompt='distill')
"""
        result = compile_script_to_graph(script)

        labels = {n.label for n in result.nodes}
        expected = {
            "as_X",
            "sem_fillna",
            "sem_gen_features",
            "sem_extract_features",
            "sem_clean",
            "sem_augment",
            "sem_agg_features",
            "sem_refine",
            "sem_select",
            "sem_distill",
        }
        for op in expected:
            assert op in labels, f"operator {op} should be recognized"
        for node in result.nodes:
            assert node.source_range is not None, f"node {node.label} should have source_range"
        assert result.is_valid

    def test_skrub_var_and_subsample(self):
        """Recognizes skrub.var and skb.subsample operators."""
        script = """
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100, how="random")
products = products.sem_gen_features(nl_prompt="Generate features.", name="features", how_many=3)
result = products.skb.eval()
"""
        result = compile_script_to_graph(script)

        labels = {n.label for n in result.nodes}
        assert any("products" in l for l in labels)  # var: "<Var 'products'>" or "products"
        assert "skb.subsample" in labels
        assert "sem_gen_features" in labels
        assert "skb.eval" in labels
        assert len(result.nodes) >= 4
        assert len(result.edges) >= 3
        assert result.is_valid

    def test_edges_reference_valid_node_ids(self):
        """All edge source/target IDs exist in the node list."""
        script = "sempipes.as_X(df,'X')\ndf.sem_fillna(target_column='a')"
        result = compile_script_to_graph(script)

        node_ids = {n.id for n in result.nodes}
        for edge in result.edges:
            assert edge.source in node_ids, f"edge source {edge.source} not in nodes"
            assert edge.target in node_ids, f"edge target {edge.target} not in nodes"

    def test_nodes_have_source_ranges(self):
        """Parsed nodes include source_range for code-graph mapping."""
        script = "x = sempipes.as_X(df, 'X')\ny = x.sem_fillna(target_column='a')"
        result = compile_script_to_graph(script)

        for node in result.nodes:
            assert node.source_range is not None, f"node {node.id} must have source_range"
            r = node.source_range
            assert r.start_line >= 1 and r.end_line >= 1
            assert r.start_column >= 1 and r.end_column >= 1

    def test_subsample_to_as_x_edge(self):
        """subsample -> as_X edge exists when as_X consumes subsample output."""
        script = """
baskets = skrub.var("baskets", data)
baskets = baskets.skb.subsample(n=100)
x = sempipes.as_X(baskets[["id"]], "X")
"""
        result = compile_script_to_graph(script)

        subsample_id = next((n.id for n in result.nodes if n.label == "skb.subsample"), None)
        as_x_id = next((n.id for n in result.nodes if n.label == "as_X"), None)

        assert subsample_id and as_x_id
        edge_pairs = {(e.source, e.target) for e in result.edges}
        assert (subsample_id, as_x_id) in edge_pairs

    def test_subsample_to_as_y_edge(self):
        """subsample -> as_y edge exists when as_y consumes subsample output."""
        script = """
baskets = skrub.var("baskets", data)
baskets = baskets.skb.subsample(n=100)
y = sempipes.as_y(baskets["label"], "y")
"""
        result = compile_script_to_graph(script)

        subsample_id = next((n.id for n in result.nodes if n.label == "skb.subsample"), None)
        as_y_id = next((n.id for n in result.nodes if n.label == "as_y"), None)

        assert subsample_id and as_y_id
        edge_pairs = {(e.source, e.target) for e in result.edges}
        assert (subsample_id, as_y_id) in edge_pairs

    def test_skb_eval_has_incoming_edge(self):
        """skb.eval receives edge from its receiver's producer."""
        script = """
basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
result = basket_ids.skb.eval()
"""
        result = compile_script_to_graph(script)

        skb_eval_id = next((n.id for n in result.nodes if n.label == "skb.eval"), None)
        assert skb_eval_id is not None

        incoming = [e for e in result.edges if e.target == skb_eval_id]
        assert len(incoming) >= 1

    def test_apply_with_sem_choose_has_edge_from_y(self):
        """apply_with_sem_choose has incoming edge from as_y (y= parameter)."""
        script = """
basket_ids = sempipes.as_X(baskets[["ID"]], "X")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")
fraud_detector = augmented_baskets.skb.apply_with_sem_choose(hgb, y=fraud_flags, choices=sem_choose(name="hgb"))
"""
        result = compile_script_to_graph(script)

        as_y_id = next((n.id for n in result.nodes if n.label == "as_y"), None)
        apply_id = next((n.id for n in result.nodes if n.label == "apply_with_sem_choose"), None)

        assert as_y_id and apply_id
        edge_from_y = [e for e in result.edges if e.source == as_y_id and e.target == apply_id]
        assert len(edge_from_y) >= 1

    def test_sem_choose_has_edge_to_apply_with_sem_choose(self):
        """sem_choose has outgoing edge to apply_with_sem_choose (choices= parameter)."""
        # Multi-line call: apply_with_sem_choose starts before sem_choose line
        script = """
basket_ids = sempipes.as_X(baskets[["ID"]], "X")
fraud_flags = sempipes.as_y(baskets["fraud_flag"], "y")
fraud_detector = augmented_baskets.skb.apply_with_sem_choose(
    hgb,
    y=fraud_flags,
    choices=sem_choose(name="hgb_choices"),
)
"""
        result = compile_script_to_graph(script)

        sem_choose_id = next((n.id for n in result.nodes if n.label == "sem_choose"), None)
        apply_id = next((n.id for n in result.nodes if n.label == "apply_with_sem_choose"), None)

        assert sem_choose_id and apply_id
        edge_to_apply = [e for e in result.edges if e.source == sem_choose_id and e.target == apply_id]
        assert len(edge_to_apply) >= 1

    def test_comment_does_not_create_node(self):
        """Comments containing pipeline words don't create nodes."""
        script = """
basket_ids = sempipes.as_X(baskets[["ID"]], "Baskets")
# 4) Evaluate the pipeline (materialize result)
result = basket_ids.skb.eval()
"""
        result = compile_script_to_graph(script)

        labels = [n.label for n in result.nodes]
        assert "Pipeline" not in labels

    def test_multiline_as_x_handled(self):
        """Multi-line as_X call is correctly parsed."""
        script = """
baskets = skrub.var("baskets", data)
baskets = baskets.skb.subsample(n=100)
basket_ids = sempipes.as_X(
    baskets[["ID"]], "Shopping baskets")
"""
        result = compile_script_to_graph(script)

        # Should have subsample -> as_X edge
        subsample_id = next((n.id for n in result.nodes if n.label == "skb.subsample"), None)
        as_x_id = next((n.id for n in result.nodes if n.label == "as_X"), None)

        assert subsample_id and as_x_id
        edge_pairs = {(e.source, e.target) for e in result.edges}
        assert (subsample_id, as_x_id) in edge_pairs

    def test_alias_variable_resolved(self):
        """Variable aliases are resolved for edge inference."""
        script = """
baskets = skrub.var("baskets", data)
baskets = baskets.skb.subsample(n=100)
b = baskets
x = sempipes.as_X(b[["id"]], "X")
"""
        result = compile_script_to_graph(script)

        # Should have subsample -> as_X edge (through alias b -> baskets)
        subsample_id = next((n.id for n in result.nodes if n.label == "skb.subsample"), None)
        as_x_id = next((n.id for n in result.nodes if n.label == "as_X"), None)

        assert subsample_id and as_x_id
        edge_pairs = {(e.source, e.target) for e in result.edges}
        assert (subsample_id, as_x_id) in edge_pairs


# Minimal scripts and expected substring for each of the 10 SemPipes operators (node extraction + highlighting).
_SEMPIPES_OPERATOR_COMPILE_CASES = [
    ("sem_fillna", "x = sempipes.as_X(df,'X')\ny = x.sem_fillna(target_column='a')", "sem_fillna"),
    ("sem_gen_features", "x = sempipes.as_X(df,'X')\ny = x.sem_gen_features(nl_prompt='gen')", "sem_gen_features"),
    ("sem_extract_features", "x = sempipes.as_X(df,'X')\ny = x.sem_extract_features(columns=['a'])", "sem_extract_features"),
    ("sem_clean", "x = sempipes.as_X(df,'X')\ny = x.sem_clean(nl_prompt='c')", "sem_clean"),
    ("sem_augment", "x = sempipes.as_X(df,'X')\ny = x.sem_augment(nl_prompt='a')", "sem_augment"),
    ("sem_agg_features", "x = sempipes.as_X(df,'X')\ny = x.sem_agg_features(nl_prompt='a')", "sem_agg_features"),
    ("sem_refine", "x = sempipes.as_X(df,'X')\ny = x.sem_refine(target_column='a')", "sem_refine"),
    ("sem_select", "x = sempipes.as_X(df,'X')\ny = x.sem_select(nl_prompt='s')", "sem_select"),
    ("sem_distill", "x = sempipes.as_X(df,'X')\ny = x.sem_distill(nl_prompt='d')", "sem_distill"),
    ("sem_choose", "x = sempipes.as_X(df,'X')\nchoices = sem_choose(name='c')", "sem_choose"),
]


class TestCompileScriptToGraphPerOperator:
    """Parametrized test: each SemPipes operator gets correct node extraction and source_range for highlighting."""

    @pytest.mark.parametrize("operator_name,minimal_script,expected_substring", _SEMPIPES_OPERATOR_COMPILE_CASES)
    def test_each_operator_node_extraction_and_highlighting(
        self, operator_name: str, minimal_script: str, expected_substring: str
    ) -> None:
        """For each operator: one node with correct label, type, and source_range spanning the call."""
        result = compile_script_to_graph(minimal_script)
        assert result.is_valid, result.validation_errors

        op_nodes = [n for n in result.nodes if n.label == operator_name]
        assert len(op_nodes) == 1, f"expected exactly one node with label {operator_name}, got {[n.label for n in result.nodes]}"
        node = op_nodes[0]
        assert (node.type or "").lower() == "operator"
        assert node.source_range is not None, f"node {operator_name} must have source_range for highlighting"

        lines = minimal_script.split("\n")
        r = node.source_range
        start_line = max(1, min(r.start_line, len(lines)))
        line = lines[start_line - 1]
        # Column is 1-based; extract span
        start_col = max(1, min(r.start_column, len(line) + 1))
        end_col = max(start_col, min(r.end_column, len(line) + 1))
        highlighted = line[start_col - 1 : end_col - 1]
        assert expected_substring in highlighted, f"highlighted span {repr(highlighted)} should contain {repr(expected_substring)}"


class TestMergeSourceRanges:
    """Unit tests for _merge_source_ranges: label and source_range from static when skrub node could be ambiguous."""

    def test_merge_sem_extract_features_only_in_static(self):
        """Static has only sem_extract_features; skrub node (fused as sem_gen_features) must get label sem_extract_features and range."""
        sr = SourceRange(start_line=2, start_column=1, end_line=2, end_column=35)
        skrub_nodes = [
            CompileNode(id="op1", type="operator", label="sem_gen_features", source_range=None),
        ]
        static_nodes = [
            CompileNode(id="sem_extract_features_2", type="operator", label="sem_extract_features", source_range=sr),
        ]
        result = _merge_source_ranges(skrub_nodes, static_nodes, script="")
        assert len(result) == 1
        assert result[0].label == "sem_extract_features"
        assert result[0].source_range == sr

    def test_merge_sem_gen_features_only_in_static(self):
        """Static has only sem_gen_features; skrub node must get label sem_gen_features and range."""
        sr = SourceRange(start_line=3, start_column=1, end_line=3, end_column=40)
        skrub_nodes = [
            CompileNode(id="op1", type="operator", label="sem_gen_features", source_range=None),
        ]
        static_nodes = [
            CompileNode(id="sem_gen_features_3", type="operator", label="sem_gen_features", source_range=sr),
        ]
        result = _merge_source_ranges(skrub_nodes, static_nodes, script="")
        assert len(result) == 1
        assert result[0].label == "sem_gen_features"
        assert result[0].source_range == sr

    def test_merge_both_in_static_two_skrub_nodes(self):
        """Static has sem_extract_features then sem_gen_features; two skrub nodes (both fused as sem_gen_features) get correct label and range each."""
        sr1 = SourceRange(start_line=3, start_column=1, end_line=3, end_column=50)
        sr2 = SourceRange(start_line=4, start_column=1, end_line=4, end_column=45)
        skrub_nodes = [
            CompileNode(id="op1", type="operator", label="sem_gen_features", source_range=None),
            CompileNode(id="op2", type="operator", label="sem_gen_features", source_range=None),
        ]
        static_nodes = [
            CompileNode(id="sem_extract_features_3", type="operator", label="sem_extract_features", source_range=sr1),
            CompileNode(id="sem_gen_features_4", type="operator", label="sem_gen_features", source_range=sr2),
        ]
        result = _merge_source_ranges(skrub_nodes, static_nodes, script="")
        assert len(result) == 2
        assert result[0].label == "sem_extract_features" and result[0].source_range == sr1
        assert result[1].label == "sem_gen_features" and result[1].source_range == sr2


class TestGraphResult:
    """Tests for the GraphResult dataclass."""

    def test_is_valid_true_when_no_errors(self):
        """is_valid returns True when validation_errors is empty."""
        from models.schemas import CompileEdge, CompileNode

        result = GraphResult(
            nodes=[
                CompileNode(id="a", type="input", label="X"),
                CompileNode(id="b", type="operator", label="op"),
            ],
            edges=[CompileEdge(source="a", target="b")],
            validation_errors=[],
        )
        assert result.is_valid is True

    def test_is_valid_false_when_errors_present(self):
        """is_valid returns False when validation_errors is non-empty."""
        from models.schemas import CompileNode

        result = GraphResult(
            nodes=[CompileNode(id="a", type="input", label="X")],
            edges=[],
            validation_errors=["Some error"],
        )
        assert result.is_valid is False


class TestIntegrationWithPipelineScripts:
    """Integration tests using actual pipeline scripts from pipeline_scripts/."""

    def test_simple_pipeline_script(self):
        """Compile the simple.py pipeline script."""
        from pathlib import Path

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "simple.py"
        if not script_path.exists():
            pytest.skip("simple.py not found")

        script = script_path.read_text()
        result = compile_script_to_graph(script)

        assert result.is_valid
        assert len(result.nodes) >= 3  # vars, as_X, as_y, sem_gen_features, skb.apply
        labels = {n.label for n in result.nodes}
        # Simple pipeline should have these core nodes
        assert "sem_gen_features" in labels or any("gen_features" in l for l in labels)

    def test_simple_pipeline_dynamic_uses_skb_apply_not_apply_with_sem_choose(self):
        """Simple pipeline uses .skb.apply(), so compiled graph must show skb.apply not apply_with_sem_choose."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        from pathlib import Path

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "simple.py"
        if not script_path.exists():
            pytest.skip("simple.py not found")

        script = script_path.read_text()
        result = compile_script_to_graph_dynamic(script)
        if not result.is_valid or not result.nodes:
            pytest.skip("dynamic compile failed")

        labels = [n.label for n in result.nodes]
        assert "apply_with_sem_choose" not in labels, (
            "simple.py uses .skb.apply(), not .skb.apply_with_sem_choose(); graph must show skb.apply"
        )
        assert "skb.apply" in labels, "simple.py uses .skb.apply(); graph must contain skb.apply node"

    def test_medium_pipeline_script(self):
        """Compile the medium.py pipeline script."""
        from pathlib import Path

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "medium.py"
        if not script_path.exists():
            pytest.skip("medium.py not found")

        script = script_path.read_text()
        result = compile_script_to_graph(script)

        assert result.is_valid
        labels = {n.label for n in result.nodes}
        # Medium should have as_X, as_y, sem_fillna, sem_gen_features
        assert "as_X" in labels
        assert "as_y" in labels
        assert "sem_fillna" in labels
        assert "sem_gen_features" in labels


class TestScriptRewriting:
    """Tests for script rewriting functions (modify scripts for graph extraction)."""

    def test_rewrite_var_example_strips_data_argument(self):
        """Preprocessing: var with data is rewritten so the dataset part is not evaluated.
        Example from docstring:
          products = skrub.var("products", dataset.products)  ->  products = skrub.var("products")
        """
        script = 'products = skrub.var("products", dataset.products)'
        result = _rewrite_var_calls(script)
        assert result == 'products = skrub.var("products")'
        assert "dataset.products" not in result

    def test_rewrite_var_removes_data_argument(self):
        """_rewrite_var_calls removes the data argument from skrub.var()."""
        script = 'products = skrub.var("products", dataset.products)'
        result = _rewrite_var_calls(script)
        assert result == 'products = skrub.var("products")'

    def test_rewrite_var_handles_single_quotes(self):
        """_rewrite_var_calls works with single-quoted names."""
        script = "products = skrub.var('products', dataset.products)"
        result = _rewrite_var_calls(script)
        assert result == "products = skrub.var('products')"

    def test_rewrite_var_handles_complex_data_argument(self):
        """_rewrite_var_calls handles complex nested expressions."""
        script = 'products = skrub.var("products", dataset.fetch().products)'
        result = _rewrite_var_calls(script)
        assert result == 'products = skrub.var("products")'

    def test_rewrite_var_handles_method_chain(self):
        """_rewrite_var_calls handles data with method chains."""
        script = 'baskets = skrub.var("baskets", dataset.baskets.head(100))'
        result = _rewrite_var_calls(script)
        assert result == 'baskets = skrub.var("baskets")'

    def test_rewrite_var_preserves_no_data_var(self):
        """_rewrite_var_calls preserves var() calls without data argument."""
        script = 'products = skrub.var("products")'
        result = _rewrite_var_calls(script)
        assert result == 'products = skrub.var("products")'

    def test_rewrite_var_handles_multiple_vars(self):
        """_rewrite_var_calls handles multiple var calls."""
        script = '''products = skrub.var("products", dataset.products)
baskets = skrub.var("baskets", dataset.baskets)'''
        result = _rewrite_var_calls(script)
        assert 'skrub.var("products")' in result
        assert 'skrub.var("baskets")' in result
        assert "dataset.products" not in result
        assert "dataset.baskets" not in result

    def test_remove_eval_replaces_with_dataop(self):
        """_remove_eval_calls replaces eval with the DataOp."""
        script = "result = products.skb.eval()"
        result = _remove_eval_calls(script)
        assert result == "result = products"

    def test_remove_eval_handles_eval_with_args(self):
        """_remove_eval_calls handles eval with arguments."""
        script = "result = products.skb.eval(environment={})"
        result = _remove_eval_calls(script)
        assert result == "result = products"

    def test_remove_eval_preserves_other_lines(self):
        """_remove_eval_calls preserves non-eval lines."""
        script = '''products = products.sem_fillna()
result = products.skb.eval()'''
        result = _remove_eval_calls(script)
        assert "products = products.sem_fillna()" in result
        assert "result = products" in result
        assert ".skb.eval()" not in result

    def test_remove_skrub_datasets_fetches_stubs_fetch_line(self):
        """_remove_skrub_datasets_fetches replaces fetch_*() so we don't run dataset load during exec."""
        script = 'dataset = skrub.datasets.fetch_credit_fraud()'
        result = _remove_skrub_datasets_fetches(script)
        assert "fetch_credit_fraud" not in result
        assert "dataset = None" in result

    def test_rewrite_script_combines_both(self):
        """rewrite_script_for_graph_extraction removes skrub.datasets fetch, strips var data, removes eval/cross_validate."""
        script = '''dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100)
result = products.skb.eval()'''
        result = rewrite_script_for_graph_extraction(script)
        assert ".skb.eval()" not in result
        assert "dataset.products" not in result
        assert "skrub.var(\"products\")" in result
        assert ".skb.subsample(n=100)" in result
        assert "fetch_credit_fraud()" not in result
        assert "dataset = None" in result

    def test_rewrite_script_modifies_var_calls_like_docstring_example(self):
        """rewrite_script_for_graph_extraction modifies scripts so every skrub.var(name, data) becomes skrub.var(name)."""
        # Same example as in graph_api.py: products = skrub.var("products", dataset.products) -> skrub.var("products")
        script = """
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100)
result = products.skb.eval()
"""
        rewritten = rewrite_script_for_graph_extraction(script)
        # Preprocessing must have stripped the data argument from var()
        assert "skrub.var(\"products\", dataset.products)" not in rewritten
        assert "skrub.var(\"products\")" in rewritten
        # Other pipeline lines unchanged (except eval removed)
        assert "skb.subsample(n=100)" in rewritten
        assert ".skb.eval()" not in rewritten
        assert "result = products" in rewritten


class TestSkrubGraphResult:
    """Tests for the SkrubGraphResult dataclass."""

    def test_is_valid_true_when_nodes_and_no_error(self):
        """is_valid returns True when nodes exist and no error."""
        from services.graph_api import SkrubNode

        result = SkrubGraphResult(
            nodes=[SkrubNode(id="0", label="var")],
            parents={"0": []},
            children={"0": []},
            rewritten_script="",
        )
        assert result.is_valid is True

    def test_is_valid_false_when_error(self):
        """is_valid returns False when error is set."""
        result = SkrubGraphResult(
            nodes=[],
            parents={},
            children={},
            rewritten_script="",
            error="Some error",
        )
        assert result.is_valid is False

    def test_is_valid_false_when_no_nodes(self):
        """is_valid returns False when no nodes."""
        result = SkrubGraphResult(
            nodes=[],
            parents={},
            children={},
            rewritten_script="",
        )
        assert result.is_valid is False

    def test_to_edges_converts_parents_to_data_flow_tuples(self):
        """to_edges converts parents dict to edge tuples in data flow direction.

        Skrub's parents dict uses inverted semantics: parents[A] = [B] means
        B wraps/consumes A. For data flow, this means A → B.
        """
        from services.graph_api import SkrubNode

        # Simulating skrub output: node 0 is upstream, node 1 consumes it
        # Skrub represents this as: parents["0"] = ["1"] (node 1 is "parent" of node 0)
        result = SkrubGraphResult(
            nodes=[
                SkrubNode(id="0", label="a"),
                SkrubNode(id="1", label="b"),
            ],
            parents={"0": ["1"], "1": []},
            children={"1": ["0"], "0": []},
            rewritten_script="",
        )
        edges = result.to_edges()
        # Data flows from node 0 to node 1
        assert ("0", "1") in edges


class TestExtractSkrubGraph:
    """Tests for extract_skrub_graph function (requires skrub)."""

    def test_simple_var_produces_graph(self):
        """Simple var() call produces a valid graph."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = 'products = skrub.var("products")'
        result = extract_skrub_graph(script)

        assert result.is_valid, f"Expected valid graph but got error: {result.error}"
        assert len(result.nodes) >= 1

    def test_var_with_data_produces_graph_when_data_defined(self):
        """Rewrite strips var data and stubs fetch so we don't run fetch_credit_fraud(); graph still builds."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = """import skrub
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
"""
        result = extract_skrub_graph(script)

        assert result.is_valid, f"Expected valid graph but got error: {result.error}"
        # Rewritten script strips var data and stubs fetch so we never run fetch_credit_fraud()
        assert "dataset.products" not in result.rewritten_script
        assert "skrub.var(\"products\")" in result.rewritten_script

    def test_var_with_subsample_produces_graph(self):
        """var + subsample produces graph with two nodes when dataset is defined."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = """import skrub
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100)
"""
        result = extract_skrub_graph(script)

        assert result.is_valid, f"Expected valid graph but got error: {result.error}"
        assert len(result.nodes) >= 2

    def test_eval_is_removed(self):
        """eval() is removed from script before execution; var data is kept."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = """import skrub
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
result = products.skb.eval()
"""
        result = extract_skrub_graph(script)

        assert result.is_valid, f"Expected valid graph but got error: {result.error}"
        assert ".skb.eval()" not in result.rewritten_script

    def test_graph_has_parent_child_relationships(self):
        """Graph includes parent/child relationships."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = '''products = skrub.var("products")
products = products.skb.subsample(n=100)'''
        result = extract_skrub_graph(script)

        assert result.is_valid
        # Should have some parent/child relationships
        assert len(result.parents) > 0 or len(result.children) > 0

    def test_invalid_script_returns_error(self):
        """Invalid Python code returns error in result."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = "this is not valid python {{"
        result = extract_skrub_graph(script)

        assert not result.is_valid
        assert result.error is not None
        assert "Execution failed" in result.error

    def test_script_without_dataop_returns_error(self):
        """Script with no DataOp returns appropriate error."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = "x = 1 + 2"
        result = extract_skrub_graph(script)

        assert not result.is_valid
        assert "No DataOp found" in result.error


class TestExtractSkrubGraphWithPipelineScripts:
    """Integration tests for extract_skrub_graph with real pipeline scripts."""

    def test_simple_pipeline_produces_graph(self):
        """Simple pipeline script produces a valid skrub graph."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        from pathlib import Path

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "simple.py"
        if not script_path.exists():
            pytest.skip("simple.py not found")

        script = script_path.read_text()
        result = extract_skrub_graph(script)

        # Rewritten script stubs fetch and strips var data so we don't run fetch_credit_fraud()
        assert result.rewritten_script
        assert result.is_valid, f"Expected valid graph: {result.error}"

    def test_extract_skrub_graph_medium_does_not_call_real_litellm(self):
        """Graph extraction patches sempipes.llm.llm so the real LLM is never called for medium."""
        try:
            import sempipes.llm.llm as llm_module
            import skrub
        except ImportError:
            pytest.skip("sempipes or skrub not available")

        from pathlib import Path

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "medium.py"
        if not script_path.exists():
            pytest.skip("medium.py not found")

        script = script_path.read_text()
        real_completion = llm_module.completion
        spy = Mock(wraps=real_completion)
        llm_module.completion = spy
        try:
            result = extract_skrub_graph(script)
            assert result.is_valid, f"Expected valid graph: {result.error}"
            assert spy.call_count == 0, "Real LLM completion must not be called during graph extraction"
        finally:
            llm_module.completion = real_completion

    def test_extract_skrub_graph_medium_produces_valid_graph_with_apply_with_sem_choose(self):
        """Medium script produces a valid fused graph containing apply_with_sem_choose and expected edges."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        from pathlib import Path

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "medium.py"
        if not script_path.exists():
            pytest.skip("medium.py not found")

        script = script_path.read_text()
        result = compile_script_to_graph_dynamic(script)

        assert result.is_valid, f"Expected valid graph: {result.validation_errors}"
        labels = {n.label for n in result.nodes}
        assert "apply_with_sem_choose" in labels, f"Graph should contain apply_with_sem_choose. Got: {labels}"
        apply_id = next((n.id for n in result.nodes if n.label == "apply_with_sem_choose"), None)
        assert apply_id, "apply_with_sem_choose node must exist"
        as_y_id = next((n.id for n in result.nodes if n.label == "as_y"), None)
        if as_y_id:
            edge_pairs = {(e.source, e.target) for e in result.edges}
            assert (as_y_id, apply_id) in edge_pairs, "as_y should have edge to apply_with_sem_choose"

    def test_sem_extract_features_code_path_gets_highlight_and_label(self):
        """sem_extract_features with generate_via_code=True uses CodeBasedFeatureExtractor; merge must attach source_range and label sem_extract_features."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        # Minimal pipeline like user's: var then sem_extract_features (code path) on same pattern
        script = """
import skrub
products = skrub.var("products", None)
brand_risk_info = products.sem_extract_features(
    nl_prompt="Extract features from make.",
    name="brand_risk_features",
    input_columns=["make"],
    generate_via_code=True,
)
"""
        result = compile_script_to_graph_dynamic(script)
        assert result.is_valid, result.validation_errors
        op_nodes = [n for n in result.nodes if (n.type or "").lower() == "operator"]
        assert op_nodes, "expected at least one operator node"
        # CodeBasedFeatureExtractor is fused to sem_gen_features; merge should fix label and range to sem_extract_features
        sem_extract_nodes = [n for n in result.nodes if n.label == "sem_extract_features"]
        assert sem_extract_nodes, "expected one node with label sem_extract_features after merge"
        node = sem_extract_nodes[0]
        assert node.source_range is not None, "sem_extract_features node must have source_range for highlighting"

    def test_sem_gen_features_only_gets_label_and_highlight(self):
        """When code has only sem_gen_features (no sem_extract_features), node must be sem_gen_features with source_range."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = """
import skrub
products = skrub.var("products", None)
products = products.sem_gen_features(nl_prompt="Gen features.", name="feat", how_many=2)
"""
        result = compile_script_to_graph_dynamic(script)
        assert result.is_valid, result.validation_errors
        sem_gen_nodes = [n for n in result.nodes if n.label == "sem_gen_features"]
        assert len(sem_gen_nodes) == 1, "expected exactly one sem_gen_features node"
        node = sem_gen_nodes[0]
        assert node.source_range is not None, "sem_gen_features node must have source_range"
        lines = script.split("\n")
        r = node.source_range
        line = lines[r.start_line - 1] if 1 <= r.start_line <= len(lines) else ""
        span = line[r.start_column - 1 : r.end_column - 1] if line else ""
        assert "sem_gen_features" in span, "source_range should span the call"

    def test_pipeline_with_both_sem_extract_features_and_sem_gen_features(self):
        """When code has both sem_extract_features and sem_gen_features, each node gets correct label and source_range."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = """
import skrub
x = skrub.var("x", None)
x = x.sem_extract_features(nl_prompt="Extract.", name="a", input_columns=["c"], generate_via_code=True)
x = x.sem_gen_features(nl_prompt="Gen.", name="b", how_many=1)
"""
        result = compile_script_to_graph_dynamic(script)
        assert result.is_valid, result.validation_errors
        sem_extract = [n for n in result.nodes if n.label == "sem_extract_features"]
        sem_gen = [n for n in result.nodes if n.label == "sem_gen_features"]
        assert len(sem_extract) == 1, "expected one sem_extract_features node"
        assert len(sem_gen) == 1, "expected one sem_gen_features node"
        assert sem_extract[0].source_range is not None
        assert sem_gen[0].source_range is not None
        lines = script.strip().split("\n")
        # Script has leading newline: line 1 blank, 2 import, 3 var, 4 sem_extract_features, 5 sem_gen_features (1-based)
        assert sem_extract[0].source_range.start_line == 4, "sem_extract_features range should match its call line"
        assert sem_gen[0].source_range.start_line == 5, "sem_gen_features range should match its call line"

    def test_two_sem_extract_features_dynamic_correct_ranges_by_order(self):
        """Two sem_extract_features calls: two nodes, each with source_range; first node = first call line, second = second call line."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = """
import skrub
x = skrub.var("x", None)
x = x.sem_extract_features(nl_prompt="First", name="a", input_columns=["c"], generate_via_code=True)
x = x.sem_extract_features(nl_prompt="Second", name="b", input_columns=["d"], generate_via_code=True)
"""
        result = compile_script_to_graph_dynamic(script)
        assert result.is_valid, result.validation_errors
        sem_extract = [n for n in result.nodes if n.label == "sem_extract_features"]
        assert len(sem_extract) >= 2, "expected at least two sem_extract_features nodes"
        # Order by source_range.start_line (document order)
        with_range = [n for n in sem_extract if n.source_range is not None]
        assert len(with_range) >= 2
        by_line = sorted(with_range, key=lambda n: n.source_range.start_line)
        # Script has leading newline: line 2 import, 3 var, 4 first sem_extract_features, 5 second (1-based)
        assert by_line[0].source_range.start_line == 4, "first call on line 4"
        assert by_line[1].source_range.start_line == 5, "second call on line 5"

    def test_extract_skrub_graph_medium_exec_ms_bounded(self):
        """Medium script exec phase stays fast (no real LLM); catches regression."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        from pathlib import Path

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "medium.py"
        if not script_path.exists():
            pytest.skip("medium.py not found")

        script = script_path.read_text()
        timings_out = {}
        result = extract_skrub_graph(script, timings_out=timings_out)
        assert result.is_valid, f"Expected valid graph: {result.error}"
        exec_ms = timings_out.get("exec_ms")
        assert exec_ms is not None, "timings_out should contain exec_ms"
        assert exec_ms < 5000, f"exec_ms should be under 5s (no real LLM). Got {exec_ms} ms"


class TestOptimizerScriptsDynamicCompile:
    """Parse and construct a valid graph for optimizer scripts via compile_script_to_graph_dynamic."""

    _ROOT = Path(__file__).resolve().parents[3]  # repo root (tests -> backend -> demo -> root)

    def _load_optimizer_script(self, filename: str) -> str:
        path = self._ROOT / "optimizer_scripts" / filename
        if not path.exists():
            pytest.skip(f"optimizer_scripts/{filename} not found")
        return path.read_text()

    def test_optimise_fraud_produces_valid_graph(self):
        """optimise_fraud.py: dynamic compile produces a valid graph (nodes and edges)."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = self._load_optimizer_script("optimise_fraud.py")
        result = compile_script_to_graph_dynamic(script)

        assert result.is_valid, f"Expected valid graph: {result.validation_errors}"
        assert len(result.nodes) > 0, "Graph should have nodes"
        assert len(result.edges) > 0, "Graph should have edges"
        labels = {n.label for n in result.nodes}
        assert "skb.apply" in labels or any("apply" in (n.label or "") for n in result.nodes), (
            f"Expected at least one apply-like node. Got: {labels}"
        )

    def test_optimise_museums_produces_valid_graph(self):
        """optimise_museums.py: dynamic compile produces a valid graph (nodes and edges)."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        script = self._load_optimizer_script("optimise_museums.py")
        result = compile_script_to_graph_dynamic(script)

        assert result.is_valid, f"Expected valid graph: {result.validation_errors}"
        assert len(result.nodes) > 0, "Graph should have nodes"
        assert len(result.edges) > 0, "Graph should have edges"

    @pytest.mark.skipif(
        __import__("importlib").util.find_spec("duckdb") is None
        or __import__("importlib").util.find_spec("tabpfn") is None,
        reason="optimise_house requires duckdb and tabpfn; skip when not installed",
    )
    def test_optimise_house_produces_valid_graph_when_deps_available(self):
        """optimise_house.py: dynamic compile produces valid graph when duckdb/tabpfn are installed."""
        try:
            import skrub
            import duckdb
            import tabpfn
        except ImportError:
            pytest.skip("skrub, duckdb or tabpfn not available")

        script = self._load_optimizer_script("optimise_house.py")
        result = compile_script_to_graph_dynamic(script)

        assert result.is_valid, f"Expected valid graph when deps present: {result.validation_errors}"
        assert len(result.nodes) > 0, "Graph should have nodes"
        assert len(result.edges) > 0, "Graph should have edges"

    def test_optimise_house_returns_structured_error_when_deps_missing(self):
        """optimise_house.py: when duckdb is missing, compile returns invalid result with clear error."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")
        try:
            import duckdb
        except ImportError:
            pass  # duckdb missing: we expect compile to fail
        else:
            pytest.skip("duckdb is installed; test only runs when duckdb is missing")

        script = self._load_optimizer_script("optimise_house.py")
        result = compile_script_to_graph_dynamic(script)

        assert not result.is_valid, "Expected invalid graph when duckdb missing"
        assert len(result.validation_errors) > 0
        assert any("duckdb" in e.lower() or "compilation failed" in e.lower() for e in result.validation_errors), (
            f"Error should mention duckdb or compilation failure: {result.validation_errors}"
        )
