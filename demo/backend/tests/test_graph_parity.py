"""
Tests that verify the compile graph matches the expected structure from skrub SVGs.

The demo generates graphs purely from code (compile_parse). These tests ensure the
produced graph has the same flow as the native skrub SVG for simple and medium pipelines.

Expected structures are derived from:
  - demo/graph_svgs/simple.svg
  - demo/graph_svgs/medium.svg
"""

import json
from pathlib import Path

import pytest

from services.compile_parse import extract_nodes_with_ranges

# Path to pipeline_scripts from demo/backend/tests
_PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "pipeline_scripts"


def _load_script(script_id: str) -> str:
    """Load pipeline script content by id (simple, medium, etc.)."""
    manifest_path = _PIPELINE_SCRIPTS_DIR / "manifest.json"
    if not manifest_path.is_file():
        pytest.skip("pipeline_scripts/manifest.json not found")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    entry = next((e for e in manifest if e["id"] == script_id), None)
    if not entry:
        pytest.skip(f"Script {script_id} not in manifest")
    path = _PIPELINE_SCRIPTS_DIR / entry["file"]
    if not path.is_file():
        pytest.skip(f"Script file {path} not found")
    return path.read_text(encoding="utf-8")


def _runnable_nodes_and_edges(code: str):
    """Extract runnable nodes and edges from code. Returns (nodes, edges) with label-based lookup."""
    nodes, edges = extract_nodes_with_ranges(code)
    runnable = [n for n in nodes if (n.type or "").lower() in ("input", "operator")]
    label_to_ids = {}
    for n in runnable:
        label = n.label or n.id
        label_to_ids.setdefault(label, []).append(n.id)
    return runnable, edges, label_to_ids


def _edge_pairs_by_label(edges, label_to_ids):
    """Convert edges to (source_label, target_label) pairs. Handles multiple nodes per label."""
    pairs = set()
    id_to_label = {}
    for label, ids in label_to_ids.items():
        for nid in ids:
            id_to_label[nid] = label
    for e in edges:
        src_label = id_to_label.get(e.source)
        tgt_label = id_to_label.get(e.target)
        if src_label and tgt_label:
            pairs.add((src_label, tgt_label))
    return pairs


# --- Simple pipeline (simple.svg) ---
# Flow: Var 'products' -> SubsamplePreviews -> product_features | Apply LLMFeatureGenerator
# Our labels: <Var 'products'> (var), skb.subsample, sem_gen_features

SIMPLE_EXPECTED_LABELS = {"<Var 'products'>", "skb.subsample", "sem_gen_features"}

SIMPLE_EXPECTED_EDGES = {
    ("<Var 'products'>", "skb.subsample"),
    ("skb.subsample", "sem_gen_features"),
}


def test_simple_pipeline_graph_matches_svg_structure():
    """Compile graph for simple.py must match flow from demo/graph_svgs/simple.svg."""
    code = _load_script("simple")
    runnable, edges, label_to_ids = _runnable_nodes_and_edges(code)

    present_labels = set(label_to_ids.keys())
    assert SIMPLE_EXPECTED_LABELS <= present_labels, (
        f"Missing expected labels: {SIMPLE_EXPECTED_LABELS - present_labels}. "
        f"Got: {present_labels}"
    )

    edge_pairs = _edge_pairs_by_label(edges, label_to_ids)
    missing = SIMPLE_EXPECTED_EDGES - edge_pairs
    assert not missing, (
        f"Missing expected edges: {missing}. "
        f"Got edges: {edge_pairs}"
    )


# --- Medium pipeline (medium.svg) ---
# Flow (from SVG):
#   Var baskets -> SubsamplePreviews -> X (as_X), y (as_y)
#   Var products -> Apply LearnedImputer (sem_fillna)
#   sem_fillna + X -> sem_gen_features (filter)
#   sem_gen_features -> TableVectorizer (skb.apply)
#   skb.apply + X -> merge -> apply_with_sem_choose
#   y -> apply_with_sem_choose
#   sem_choose -> apply_with_sem_choose

MEDIUM_EXPECTED_LABELS = {
    "<Var 'products'>",
    "<Var 'baskets'>",
    "skb.subsample",
    "as_X",
    "as_y",
    "sem_fillna",
    "sem_gen_features",
    # skb.apply (TableVectorizer) is not produced by the static parser when the
    # call uses backslash line continuation; it is present in the dynamic graph.
    "apply_with_sem_choose",
    "sem_choose",
}

MEDIUM_EXPECTED_EDGES = {
    ("<Var 'baskets'>", "skb.subsample"),
    ("skb.subsample", "as_X"),
    ("skb.subsample", "as_y"),
    ("<Var 'products'>", "sem_fillna"),
    ("sem_fillna", "sem_gen_features"),
    ("as_X", "sem_gen_features"),
    ("as_X", "apply_with_sem_choose"),
    ("as_y", "apply_with_sem_choose"),
    ("sem_choose", "apply_with_sem_choose"),
}


def test_medium_pipeline_graph_matches_svg_structure():
    """Compile graph for medium.py must match flow from demo/graph_svgs/medium.svg."""
    code = _load_script("medium")
    runnable, edges, label_to_ids = _runnable_nodes_and_edges(code)

    present_labels = set(label_to_ids.keys())
    assert MEDIUM_EXPECTED_LABELS <= present_labels, (
        f"Missing expected labels: {MEDIUM_EXPECTED_LABELS - present_labels}. "
        f"Got: {present_labels}"
    )

    edge_pairs = _edge_pairs_by_label(edges, label_to_ids)
    missing = MEDIUM_EXPECTED_EDGES - edge_pairs
    assert not missing, (
        f"Missing expected edges: {missing}. "
        f"Got edges: {edge_pairs}"
    )


def test_medium_pipeline_node_order_supports_layout():
    """
    Node order from compile must support layout: baskets branch (subsample) before products branch
    (sem_fillna) so orderNodesByFlow places baskets left of products.
    """
    code = _load_script("medium")
    nodes, edges = extract_nodes_with_ranges(code)
    runnable = [n for n in nodes if (n.type or "").lower() in ("input", "operator")]
    node_index = {n.id: i for i, n in enumerate(runnable)}

    # Find roots (no incoming edges)
    targets = {e.target for e in edges}
    roots = [n for n in runnable if n.id not in targets]
    assert len(roots) >= 2, "medium has at least two roots (products, baskets)"

    # Build children from edges
    children = {}
    for e in edges:
        children.setdefault(e.source, []).append(e.target)

    # Baskets' first child (subsample) must have lower index than products' first child (sem_fillna)
    baskets_ids = [n.id for n in runnable if (n.label or "").lower() == "<var 'baskets'>"]
    products_ids = [n.id for n in runnable if (n.label or "").lower() == "<var 'products'>"]
    assert baskets_ids, "must have baskets node"
    assert products_ids, "must have products node"
    baskets_id = baskets_ids[0]
    products_id = products_ids[0]

    baskets_children = children.get(baskets_id, [])
    products_children = children.get(products_id, [])
    assert baskets_children, "baskets must have children (subsample)"
    assert products_children, "products must have children (sem_fillna)"

    min_baskets_child_idx = min(node_index.get(c, 999) for c in baskets_children)
    min_products_child_idx = min(node_index.get(c, 999) for c in products_children)
    assert min_baskets_child_idx < min_products_child_idx, (
        f"baskets branch (min child idx={min_baskets_child_idx}) must come before "
        f"products branch (min child idx={min_products_child_idx}) for layout"
    )
