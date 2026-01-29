"""
Extract sempipe-like elements from pipeline source for code–graph mapping.
Inspired by sempipes/demo.ipynb: as_X, as_y, sem_fillna, sem_gen_features,
skb.apply, apply_with_sem_choose, sem_choose. Also supports legacy source/op/pipeline.
Uses simple regex/line scan; does not depend on sempipes. For production,
the scrub compiler could provide precise ranges.
"""

import re

from models.schemas import CompileEdge, CompileNode, SourceRange


def _find_call_ranges(text: str) -> list[tuple[int, int, int, int, str, str, str]]:
    """Find sempipe-style calls. Returns (start_line, start_col, end_line, end_col, node_id, type, label)."""
    results: list[tuple[int, int, int, int, str, str, str]] = []
    lines = text.split("\n")

    # Notebook-style: as_X(..., "desc") / as_y(..., "desc")
    as_x_pat = re.compile(r"\bas_X\s*\(")
    as_y_pat = re.compile(r"\bas_y\s*\(")
    # Notebook-style: .sem_fillna(, .sem_gen_features(, .skb.apply(, .skb.apply_with_sem_choose(
    sem_fillna_pat = re.compile(r"\.sem_fillna\s*\(")
    sem_gen_features_pat = re.compile(r"\.sem_gen_features\s*\(")
    skb_apply_pat = re.compile(r"\.skb\.apply\s*\(")
    apply_with_sem_choose_pat = re.compile(r"\.skb\.apply_with_sem_choose\s*\(")
    sem_choose_pat = re.compile(r"\bsem_choose\s*\(")
    # Legacy: source(...), op(...), pipeline(
    source_pat = re.compile(r'\bsource\s*\(\s*["\']([^"\']*)["\']\s*\)')
    op_pat = re.compile(r'\bop\s*\(\s*["\']([^"\']*)["\']\s*\)')
    pipeline_pat = re.compile(r"\bpipeline\s*\(")

    def add(line_no: int, start: int, end: int, node_id: str, node_type: str, label: str) -> None:
        results.append((line_no, start + 1, line_no, end, node_id, node_type, label))

    for one_indexed_line, line in enumerate(lines, start=1):
        # Notebook-style inputs
        for m in as_x_pat.finditer(line):
            add(one_indexed_line, m.start(), m.end(), f"as_X_{one_indexed_line}", "input", "as_X")
        for m in as_y_pat.finditer(line):
            add(one_indexed_line, m.start(), m.end(), f"as_y_{one_indexed_line}", "input", "as_y")
        # Notebook-style operators
        for m in sem_fillna_pat.finditer(line):
            add(one_indexed_line, m.start(), m.end(), f"sem_fillna_{one_indexed_line}", "operator", "sem_fillna")
        for m in sem_gen_features_pat.finditer(line):
            add(
                one_indexed_line,
                m.start(),
                m.end(),
                f"sem_gen_features_{one_indexed_line}",
                "operator",
                "sem_gen_features",
            )
        for m in skb_apply_pat.finditer(line):
            add(one_indexed_line, m.start(), m.end(), f"skb_apply_{one_indexed_line}", "operator", "skb.apply")
        for m in apply_with_sem_choose_pat.finditer(line):
            add(
                one_indexed_line,
                m.start(),
                m.end(),
                f"apply_with_sem_choose_{one_indexed_line}",
                "operator",
                "apply_with_sem_choose",
            )
        for m in sem_choose_pat.finditer(line):
            add(one_indexed_line, m.start(), m.end(), f"sem_choose_{one_indexed_line}", "operator", "sem_choose")
        # Legacy
        for m in source_pat.finditer(line):
            label = m.group(1) if m.lastindex else "input"
            add(one_indexed_line, m.start(), m.end(), f"input_{label}", "input", label)
        for m in op_pat.finditer(line):
            label = m.group(1) if m.lastindex else "op"
            add(one_indexed_line, m.start(), m.end(), f"op_{label}_{one_indexed_line}", "operator", label)
        for m in pipeline_pat.finditer(line):
            add(one_indexed_line, m.start(), m.end(), f"pipeline_{one_indexed_line}", "pipeline", "Pipeline")

    return results


def _infer_edges(nodes: list[CompileNode]) -> list[CompileEdge]:
    """Infer edges from document order: linear chain (source flow). Matches sempipes-style pipeline DAG."""
    edges: list[CompileEdge] = []
    for i in range(len(nodes) - 1):
        edges.append(CompileEdge(source=nodes[i].id, target=nodes[i + 1].id))
    return edges


def extract_nodes_with_ranges(input_code: str) -> tuple[list[CompileNode], list[CompileEdge]]:
    """Parse pipeline source and return graph nodes (with source ranges) and edges for graph sync."""
    raw = _find_call_ranges(input_code)
    seen: set[str] = set()
    nodes: list[CompileNode] = []
    for start_line, start_col, end_line, end_col, node_id, node_type, label in raw:
        if node_id in seen:
            continue
        seen.add(node_id)
        nodes.append(
            CompileNode(
                id=node_id,
                type=node_type,
                label=label,
                source_range=SourceRange(
                    start_line=start_line,
                    start_column=start_col,
                    end_line=end_line,
                    end_column=end_col,
                ),
            )
        )
    # If nothing found, return a minimal default so UI still works
    if not nodes:
        nodes = [
            CompileNode(
                id="input",
                type="input",
                label="Input",
                source_range=None,
            ),
            CompileNode(
                id="op1",
                type="operator",
                label="Op",
                source_range=None,
            ),
        ]
    edges = _infer_edges(nodes)
    return nodes, edges
