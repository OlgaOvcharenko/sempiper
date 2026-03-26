"""
Tests for the graph fusion module.

The fusion module collapses sempipes internal nodes into single semantic
operator nodes for a cleaner user-facing graph.

Tests cover all sempipes operators:
- sem_fillna
- sem_gen_features
- sem_select
- sem_augment
- sem_clean
- sem_refine
- sem_agg_features
- sem_distill
- sem_extract_features
- apply_with_sem_choose
"""

import pytest

from models.schemas import CompileEdge, CompileNode, SourceRange
from services.graph_fusion import (
    FusionResult,
    fuse_graph,
    fuse_sempipes_nodes,
    _is_sempipes_internal_node,
    _is_sempipes_internal_var,
    _get_sempipes_operator_label,
    _OPERATOR_MAPPINGS,
)


class TestInternalVariableDetection:
    """Tests for identifying sempipes internal variables."""

    @pytest.mark.parametrize("var_name", [
        "sempipes_inspirations__brand_features",
        "sempipes_memory__brand_features",
        "sempipes_pipeline_summary__brand_features",
        "sempipes_prefitted_state__brand_features",
        "sempipes_fitted_estimator__augmented_data",
        "sempipes__choices__hgb_choices__choices",
        "sempipes__choices__hgb_choices__estimator",
    ])
    def test_sempipes_internal_vars_detected(self, var_name):
        """All sempipes internal variable patterns should be detected."""
        label = f"<Var '{var_name}'>"
        assert _is_sempipes_internal_var(label), f"{var_name} should be internal"

    @pytest.mark.parametrize("var_name", [
        "products",
        "baskets",
        "fraud_flags",
        "basket_ids",
        "my_custom_var",
    ])
    def test_regular_vars_not_internal(self, var_name):
        """Regular user variables should not be detected as internal."""
        label = f"<Var '{var_name}'>"
        assert not _is_sempipes_internal_var(label), f"{var_name} should not be internal"


class TestInternalNodeDetection:
    """Tests for identifying sempipes internal nodes (vars + special nodes)."""

    def test_evalmode_is_internal(self):
        assert _is_sempipes_internal_node("<EvalMode>")

    def test_store_sem_choices_is_internal(self):
        assert _is_sempipes_internal_node("<Call 'store_sem_choices'>")

    def test_value_dict_is_internal(self):
        # <Value dict> is a skrub-internal node used by sem_agg_features to bundle inputs
        assert _is_sempipes_internal_node("<Value dict>")
        assert _is_sempipes_internal_node("<value dict>")  # case-insensitive

    def test_internal_vars_detected_as_internal_nodes(self):
        assert _is_sempipes_internal_node("<Var 'sempipes_inspirations__features'>")
        assert _is_sempipes_internal_node("<Var 'sempipes_memory__features'>")

    @pytest.mark.parametrize("label", [
        "<Var 'products'>",
        "<SubsamplePreviews>",
        "<Apply LLMFeatureGenerator>",
        "<Apply LearnedImputer>",
        "<GetItem 'col'>",
        "<CallMethod 'merge'>",
    ])
    def test_regular_nodes_not_internal(self, label):
        """Regular skrub nodes should not be detected as internal."""
        assert not _is_sempipes_internal_node(label), f"{label} should not be internal"


class TestSemFillnaMapping:
    """Tests for sem_fillna operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply LLMImputer>", "sem_fillna"),
        ("<Apply LearnedImputer>", "sem_fillna"),
        ("<Apply ImputedLearner>", "sem_fillna"),
        ("<Apply SemFillNAWithLLM>", "sem_fillna"),
        ("<Apply SemFillNALLLMPlusModel>", "sem_fillna"),
    ])
    def test_fillna_class_mappings(self, class_name, expected):
        """All sem_fillna implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemGenFeaturesMapping:
    """Tests for sem_gen_features operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply LLMFeatureGenerator>", "sem_gen_features"),
        ("<Apply CAAFE>", "sem_gen_features"),
        ("<Apply SemGenFeaturesCaafe>", "sem_gen_features"),
    ])
    def test_gen_features_class_mappings(self, class_name, expected):
        """All sem_gen_features implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemSelectMapping:
    """Tests for sem_select operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply SelectCols>", "sem_select"),
        ("<Apply SemSelectLLM>", "sem_select"),
        ("<Apply Filter>", "sem_select"),
    ])
    def test_select_class_mappings(self, class_name, expected):
        """All sem_select implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemAugmentMapping:
    """Tests for sem_augment operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply CodeDataAugmentor>", "sem_augment"),
        ("<Apply DirectDataAugmentor>", "sem_augment"),
        ("<Apply CodeAugmentor>", "sem_augment"),
        ("<Apply SemAugmentData>", "sem_augment"),
    ])
    def test_augment_class_mappings(self, class_name, expected):
        """All sem_augment implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemCleanMapping:
    """Tests for sem_clean operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply LLMCleaner>", "sem_clean"),
        ("<Apply SemCleanWithLLM>", "sem_clean"),
    ])
    def test_clean_class_mappings(self, class_name, expected):
        """All sem_clean implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemRefineMapping:
    """Tests for sem_refine operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply LLMDeduplicator>", "sem_refine"),
        ("<Apply SemRefineWithLLM>", "sem_refine"),
    ])
    def test_refine_class_mappings(self, class_name, expected):
        """All sem_refine implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemAggFeaturesMapping:
    """Tests for sem_agg_features operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply LLMCodeGenSemAggFeaturesEstimator>", "sem_agg_features"),
        ("<Apply SemAggFeatures>", "sem_agg_features"),
    ])
    def test_agg_features_class_mappings(self, class_name, expected):
        """All sem_agg_features implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemDistillMapping:
    """Tests for sem_distill operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply CodeDataDistiller>", "sem_distill"),
        ("<Apply SemDistillData>", "sem_distill"),
    ])
    def test_distill_class_mappings(self, class_name, expected):
        """All sem_distill implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestSemExtractFeaturesMapping:
    """Tests for sem_extract_features operator mapping."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply LLMFeatureExtractor>", "sem_extract_features"),
        ("<Apply SemExtractFeaturesLLM>", "sem_extract_features"),
        ("<Apply CodeBasedFeatureExtractor>", "sem_extract_features"),
    ])
    def test_extract_features_class_mappings(self, class_name, expected):
        """All sem_extract_features implementation classes should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestApplyWithSemChooseMapping:
    """Tests for apply_with_sem_choose operator mapping (sklearn estimators)."""

    @pytest.mark.parametrize("class_name,expected", [
        ("<Apply HistGradientBoostingClassifier>", "apply_with_sem_choose"),
        ("<Apply HistGradientBoostingRegressor>", "apply_with_sem_choose"),
        ("<Apply RandomForestClassifier>", "apply_with_sem_choose"),
        ("<Apply RandomForestRegressor>", "apply_with_sem_choose"),
        ("<Apply GradientBoostingClassifier>", "apply_with_sem_choose"),
        ("<Apply GradientBoostingRegressor>", "apply_with_sem_choose"),
        ("<Apply XGBClassifier>", "apply_with_sem_choose"),
        ("<Apply XGBRegressor>", "apply_with_sem_choose"),
        ("<Apply LGBMClassifier>", "apply_with_sem_choose"),
        ("<Apply LGBMRegressor>", "apply_with_sem_choose"),
    ])
    def test_sklearn_estimator_mappings(self, class_name, expected):
        """Common sklearn estimators used with sem_choose should map correctly."""
        assert _get_sempipes_operator_label(class_name) == expected


class TestUnmappedLabelsUnchanged:
    """Tests that unmapped labels are left unchanged."""

    @pytest.mark.parametrize("label", [
        "<Var 'products'>",
        "<SubsamplePreviews>",
        "<GetItem 'col'>",
        "<CallMethod 'merge'>",
        "<Apply TableVectorizer>",
        "<Apply UnknownEstimator>",
    ])
    def test_unmapped_labels_unchanged(self, label):
        """Labels without mappings should be returned unchanged."""
        assert _get_sempipes_operator_label(label) == label


class TestFusionRemovesInternalNodes:
    """Tests for node removal during fusion."""

    def test_removes_all_internal_var_types(self):
        """All types of internal vars should be removed."""
        nodes = [
            CompileNode(id="0", type="input", label="<Var 'products'>"),
            CompileNode(id="1", type="input", label="<Var 'sempipes_inspirations__features'>"),
            CompileNode(id="2", type="input", label="<Var 'sempipes_memory__features'>"),
            CompileNode(id="3", type="input", label="<Var 'sempipes_pipeline_summary__features'>"),
            CompileNode(id="4", type="input", label="<Var 'sempipes_prefitted_state__features'>"),
            CompileNode(id="5", type="input", label="<Var 'sempipes_fitted_estimator__aug'>"),
            CompileNode(id="6", type="input", label="<Var 'sempipes__choices__hgb__choices'>"),
            CompileNode(id="7", type="operator", label="<Apply LLMFeatureGenerator>"),
        ]
        edges = []

        result = fuse_sempipes_nodes(nodes, edges)

        # Should only have products and sem_gen_features
        assert len(result.nodes) == 2
        labels = {n.label for n in result.nodes}
        assert "<Var 'products'>" in labels
        assert "sem_gen_features" in labels
        assert result.fused_count == 6

    def test_removes_evalmode(self):
        """EvalMode nodes should be removed."""
        nodes = [
            CompileNode(id="0", type="input", label="<Var 'products'>"),
            CompileNode(id="1", type="operator", label="<EvalMode>"),
            CompileNode(id="2", type="operator", label="<Apply LLMFeatureGenerator>"),
        ]
        edges = []

        result = fuse_sempipes_nodes(nodes, edges)
        labels = {n.label for n in result.nodes}
        assert "<EvalMode>" not in labels

    def test_removes_store_sem_choices(self):
        """store_sem_choices nodes should be removed."""
        nodes = [
            CompileNode(id="0", type="input", label="<Var 'products'>"),
            CompileNode(id="1", type="operator", label="<Call 'store_sem_choices'>"),
        ]
        edges = []

        result = fuse_sempipes_nodes(nodes, edges)
        labels = {n.label for n in result.nodes}
        assert "store_sem_choices" not in str(labels)


class TestFusionEdgeRedirection:
    """Tests for edge redirection during fusion."""

    def test_redirects_edges_around_removed_nodes(self):
        """Edges should be redirected around removed nodes."""
        nodes = [
            CompileNode(id="0", type="input", label="<Var 'products'>"),
            CompileNode(id="1", type="input", label="<Var 'sempipes_memory__features'>"),
            CompileNode(id="2", type="operator", label="<Apply LLMFeatureGenerator>"),
        ]
        edges = [
            CompileEdge(source="0", target="1"),
            CompileEdge(source="1", target="2"),
        ]

        result = fuse_sempipes_nodes(nodes, edges)

        edge_pairs = {(e.source, e.target) for e in result.edges}
        assert ("0", "2") in edge_pairs

    def test_handles_multiple_internal_nodes_in_chain(self):
        """Multiple internal nodes in a chain should all be removed."""
        nodes = [
            CompileNode(id="0", type="input", label="<Var 'products'>"),
            CompileNode(id="1", type="input", label="<Var 'sempipes_inspirations__feat'>"),
            CompileNode(id="2", type="input", label="<Var 'sempipes_memory__feat'>"),
            CompileNode(id="3", type="operator", label="<EvalMode>"),
            CompileNode(id="4", type="operator", label="<Apply LLMFeatureGenerator>"),
        ]
        edges = [
            CompileEdge(source="0", target="1"),
            CompileEdge(source="1", target="2"),
            CompileEdge(source="2", target="3"),
            CompileEdge(source="3", target="4"),
        ]

        result = fuse_sempipes_nodes(nodes, edges)

        # Should only have products -> sem_gen_features
        assert len(result.nodes) == 2
        edge_pairs = {(e.source, e.target) for e in result.edges}
        assert ("0", "4") in edge_pairs


class TestFusionPreservesSourceRanges:
    """Tests for source range preservation."""

    def test_preserves_source_ranges(self):
        """Source ranges should be preserved through fusion."""
        sr = SourceRange(start_line=10, start_column=1, end_line=10, end_column=20)
        nodes = [
            CompileNode(id="0", type="operator", label="<Apply LearnedImputer>", source_range=sr),
        ]
        edges = []

        result = fuse_sempipes_nodes(nodes, edges)

        assert len(result.nodes) == 1
        assert result.nodes[0].source_range == sr
        assert result.nodes[0].label == "sem_fillna"


class TestFuseGraphConvenience:
    """Tests for the convenience fuse_graph function."""

    def test_returns_tuple_of_nodes_and_edges(self):
        nodes = [CompileNode(id="0", type="input", label="<Var 'products'>")]
        edges = []

        new_nodes, new_edges = fuse_graph(nodes, edges)

        assert isinstance(new_nodes, list)
        assert isinstance(new_edges, list)
        assert len(new_nodes) == 1


class TestAllOperatorMappingsExist:
    """Meta-tests to ensure all operators have mappings."""

    def test_all_sempipes_operators_have_mappings(self):
        """Ensure we have mappings for all documented operators."""
        expected_operators = {
            "sem_fillna",
            "sem_gen_features",
            "sem_select",
            "sem_augment",
            "sem_clean",
            "sem_refine",
            "sem_agg_features",
            "sem_distill",
            "sem_extract_features",
            "apply_with_sem_choose",
        }

        mapped_operators = set(_OPERATOR_MAPPINGS.values())

        assert expected_operators == mapped_operators, (
            f"Missing operators: {expected_operators - mapped_operators}, "
            f"Extra operators: {mapped_operators - expected_operators}"
        )


class TestIntegrationWithRealPipelines:
    """Integration tests with actual pipeline scripts."""

    def test_medium_pipeline_fusion(self):
        """Medium pipeline should have fewer nodes after fusion."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        from pathlib import Path
        from services.graph_api import compile_script_to_graph_dynamic

        script_path = Path(__file__).parent.parent.parent.parent / "pipeline_scripts" / "medium.py"
        if not script_path.exists():
            pytest.skip("medium.py not found")

        script = script_path.read_text()
        result = compile_script_to_graph_dynamic(script)

        # Check that sempipes operators are present with clean names
        labels = {n.label for n in result.nodes}

        # Should have at least one of the main operators
        has_sempipes_op = any(
            op in labels
            for op in ["sem_fillna", "sem_gen_features", "apply_with_sem_choose"]
        )
        assert has_sempipes_op, f"Should have sempipes operators. Got: {labels}"

        # Check that internal vars are removed
        for label in labels:
            assert "sempipes_inspirations" not in label
            assert "sempipes_memory" not in label
            assert "sempipes_pipeline_summary" not in label
            assert "sempipes_prefitted_state" not in label
            assert "sempipes_fitted_estimator" not in label
            assert "sempipes__choices" not in label

    def test_simple_pipeline_with_fusion(self):
        """Simple pipeline should work with fusion when dataset is defined."""
        try:
            import skrub
        except ImportError:
            pytest.skip("skrub not available")

        from services.graph_api import compile_script_to_graph_dynamic

        script = """
import skrub
dataset = skrub.datasets.fetch_credit_fraud()
products = skrub.var("products", dataset.products)
products = products.skb.subsample(n=100)
"""
        result = compile_script_to_graph_dynamic(script)

        assert len(result.nodes) >= 2, f"expected >=2 nodes, got {result.validation_errors}"
        labels = {n.label for n in result.nodes}
        assert any("products" in l.lower() for l in labels)
