"""
Graph fusion module for collapsing sempipes internal nodes into single semantic operators.

Sempipes operators create internal skrub nodes that should be hidden from users:

Internal Variables (created by ContextAwareMixin, OptimisableMixin):
- sempipes_inspirations__{name} - operator inspirations/context
- sempipes_memory__{name} - operator memory state
- sempipes_pipeline_summary__{name} - pipeline summary
- sempipes_prefitted_state__{name} - prefitted state
- sempipes_fitted_estimator__{name} - fitted estimator (sem_augment)
- sempipes__choices__{name}__choices - sem_choose choices
- sempipes__choices__{name}__estimator - sem_choose estimator

Internal Nodes:
- <EvalMode> - internal evaluation mode marker
- <Call 'store_sem_choices'> - internal choice storage

Operator Mappings (skrub Apply classes -> sempipes operators):

sem_fillna:
  - LLMImputer, LearnedImputer, ImputedLearner
  - SemFillNAWithLLM, SemFillNALLLMPlusModel

sem_gen_features:
  - LLMFeatureGenerator, CodeBasedFeatureExtractor, CAAFE

sem_select:
  - SelectCols, SemSelectLLM

sem_augment:
  - CodeDataAugmentor, DirectDataAugmentor, CodeAugmentor

sem_clean:
  - LLMCleaner, SemCleanWithLLM

sem_refine:
  - LLMDeduplicator, SemRefineWithLLM

sem_agg_features:
  - LLMCodeGenSemAggFeaturesEstimator, SemAggFeatures

sem_distill:
  - CodeDataDistiller, SemDistillData

sem_extract_features:
  - LLMFeatureExtractor, SemExtractFeaturesLLM

apply_with_sem_choose:
  - Any sklearn estimator with sem_choose (e.g., HistGradientBoostingClassifier)
"""

import re
from dataclasses import dataclass
from models.schemas import CompileEdge, CompileNode, SourceRange


@dataclass
class FusionResult:
    """Result of fusing a graph."""
    nodes: list[CompileNode]
    edges: list[CompileEdge]
    fused_count: int  # Number of nodes that were fused/removed


# Patterns for sempipes internal variables
_INTERNAL_VAR_PATTERNS = [
    "sempipes_inspirations__",
    "sempipes_memory__",
    "sempipes_pipeline_summary__",
    "sempipes_prefitted_state__",
    "sempipes_fitted_estimator__",
    "sempipes__choices__",
]


def _is_sempipes_internal_var(label: str) -> bool:
    """Check if this is a sempipes internal variable that should be hidden."""
    if not label:
        return False
    low = label.lower()
    for pattern in _INTERNAL_VAR_PATTERNS:
        if pattern in low:
            return True
    return False


def _is_sempipes_internal_node(label: str) -> bool:
    """Check if this is any sempipes internal node that should be hidden."""
    if not label:
        return False
    low = label.lower()

    # Internal vars
    if _is_sempipes_internal_var(low):
        return True

    # EvalMode is internal
    if low == "<evalmode>" or "evalmode" in low:
        return True

    # store_sem_choices is internal
    if "store_sem_choices" in low:
        return True

    return False


def _extract_operator_name_from_var(label: str) -> str | None:
    """Extract the operator name from a sempipes internal var.

    Examples:
        <Var 'sempipes_inspirations__brand_features'> -> brand_features
        <Var 'sempipes__choices__hgb_choices__choices'> -> hgb_choices
    """
    if not label:
        return None

    # Match sempipes_X__name pattern
    match = re.search(r"sempipes_\w+__(\w+)", label.lower())
    if match:
        return match.group(1)

    # Match sempipes__choices__name__choices pattern
    match = re.search(r"sempipes__choices__(\w+)__", label.lower())
    if match:
        return match.group(1)

    return None


# Mapping from skrub internal class names to sempipes operator names
_OPERATOR_MAPPINGS = {
    # sem_fillna
    "llmimputer": "sem_fillna",
    "learnedimputer": "sem_fillna",
    "imputedlearner": "sem_fillna",
    "semfillnawithllm": "sem_fillna",
    "semfillnalllmplusmodel": "sem_fillna",

    # sem_gen_features
    "llmfeaturegenerator": "sem_gen_features",
    "codebasedfeatureextractor": "sem_gen_features",
    "caafe": "sem_gen_features",
    "semgenfeaturescaafe": "sem_gen_features",

    # sem_select
    "selectcols": "sem_select",
    "semselectllm": "sem_select",
    "filter": "sem_select",

    # sem_augment
    "codedataaugmentor": "sem_augment",
    "directdataaugmentor": "sem_augment",
    "codeaugmentor": "sem_augment",
    "semaugmentdata": "sem_augment",

    # sem_clean
    "llmcleaner": "sem_clean",
    "semcleanwithllm": "sem_clean",

    # sem_refine
    "llmdeduplicator": "sem_refine",
    "semrefinewithllm": "sem_refine",

    # sem_agg_features
    "llmcodegensemaggfeaturesestimator": "sem_agg_features",
    "llmcodegensemaaggjoinfeaturesoperator": "sem_agg_features",
    "semaggfeatures": "sem_agg_features",

    # sem_distill
    "codedatadistiller": "sem_distill",
    "semdistilldata": "sem_distill",

    # sem_extract_features
    "llmfeatureextractor": "sem_extract_features",
    "semextractfeaturesllm": "sem_extract_features",

    # apply_with_sem_choose (common sklearn estimators used with sem_choose)
    "histgradientboostingclassifier": "apply_with_sem_choose",
    "histgradientboostingregressor": "apply_with_sem_choose",
    "randomforestclassifier": "apply_with_sem_choose",
    "randomforestregressor": "apply_with_sem_choose",
    "gradientboostingclassifier": "apply_with_sem_choose",
    "gradientboostingregressor": "apply_with_sem_choose",
    "xgbclassifier": "apply_with_sem_choose",
    "xgbregressor": "apply_with_sem_choose",
    "lgbmclassifier": "apply_with_sem_choose",
    "lgbmregressor": "apply_with_sem_choose",
}


def _get_sempipes_operator_label(label: str) -> str:
    """Map raw skrub Apply labels to sempipes operator names.

    Examples:
        <Apply LLMFeatureGenerator> -> sem_gen_features
        <Apply LearnedImputer> -> sem_fillna
        <Apply HistGradientBoostingClassifier> -> apply_with_sem_choose
    """
    if not label:
        return label

    low = label.lower()

    # Check for direct matches in the mapping
    for class_name, operator_name in _OPERATOR_MAPPINGS.items():
        if class_name in low:
            return operator_name

    return label


def fuse_sempipes_nodes(
    nodes: list[CompileNode],
    edges: list[CompileEdge],
) -> FusionResult:
    """
    Fuse sempipes internal nodes into their parent operators.

    This collapses internal implementation details (inspirations, memory, etc.)
    into single semantic operator nodes for a cleaner user-facing graph.

    Args:
        nodes: List of graph nodes
        edges: List of graph edges

    Returns:
        FusionResult with fused nodes and updated edges
    """
    # Identify nodes to remove (internal sempipes nodes)
    nodes_to_remove: set[str] = set()
    for node in nodes:
        if _is_sempipes_internal_node(node.label):
            nodes_to_remove.add(node.id)

    # Build node lookup
    node_by_id = {n.id: n for n in nodes}

    # Build edge maps
    incoming_edges: dict[str, list[str]] = {n.id: [] for n in nodes}  # target -> sources
    outgoing_edges: dict[str, list[str]] = {n.id: [] for n in nodes}  # source -> targets

    for edge in edges:
        if edge.target in incoming_edges:
            incoming_edges[edge.target].append(edge.source)
        if edge.source in outgoing_edges:
            outgoing_edges[edge.source].append(edge.target)

    # For each removed node, redirect its edges
    # If A -> removed -> B, create A -> B
    redirected_edges: set[tuple[str, str]] = set()

    for removed_id in nodes_to_remove:
        sources = incoming_edges.get(removed_id, [])
        targets = outgoing_edges.get(removed_id, [])

        # Connect all sources to all targets (skip if source or target is also removed)
        for src in sources:
            if src not in nodes_to_remove:
                for tgt in targets:
                    if tgt not in nodes_to_remove:
                        redirected_edges.add((src, tgt))

    # Build new node list (excluding removed nodes, with renamed labels)
    new_nodes = []
    for node in nodes:
        if node.id in nodes_to_remove:
            continue

        # Rename Apply nodes to sempipes operator names
        new_label = _get_sempipes_operator_label(node.label)

        new_nodes.append(CompileNode(
            id=node.id,
            type=node.type,
            label=new_label,
            source_range=node.source_range,
        ))

    # Build new edge list
    new_edges = []
    seen_edges: set[tuple[str, str]] = set()

    # Add original edges (excluding those involving removed nodes)
    for edge in edges:
        if edge.source in nodes_to_remove or edge.target in nodes_to_remove:
            continue
        if (edge.source, edge.target) not in seen_edges:
            seen_edges.add((edge.source, edge.target))
            new_edges.append(edge)

    # Add redirected edges
    for src, tgt in redirected_edges:
        if (src, tgt) not in seen_edges:
            seen_edges.add((src, tgt))
            new_edges.append(CompileEdge(source=src, target=tgt))

    return FusionResult(
        nodes=new_nodes,
        edges=new_edges,
        fused_count=len(nodes_to_remove),
    )


def fuse_graph(
    nodes: list[CompileNode],
    edges: list[CompileEdge],
) -> tuple[list[CompileNode], list[CompileEdge]]:
    """
    Convenience function to fuse a graph and return nodes/edges directly.

    Args:
        nodes: List of graph nodes
        edges: List of graph edges

    Returns:
        Tuple of (fused_nodes, fused_edges)
    """
    result = fuse_sempipes_nodes(nodes, edges)
    return result.nodes, result.edges
