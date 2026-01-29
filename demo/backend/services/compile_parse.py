"""
Extract sempipe-like elements from pipeline source for code–graph mapping.
Uses simple regex/line scan; does not depend on sempipes. For production,
the scrub compiler could provide precise ranges.
"""
import re
from models.schemas import CompileNode, SourceRange


def _find_call_ranges(text: str) -> list[tuple[int, int, int, int, str, str, str]]:
    """Find source(...), op(...), pipeline(...) calls. Returns (start_line, start_col, end_line, end_col, node_id, type, label)."""
    results: list[tuple[int, int, int, int, str, str, str]] = []
    lines = text.split("\n")
    # Match source("..."), op("..."), pipeline( with flexible spacing
    source_pat = re.compile(r'\bsource\s*\(\s*["\']([^"\']*)["\']\s*\)')
    op_pat = re.compile(r'\bop\s*\(\s*["\']([^"\']*)["\']\s*\)')
    pipeline_pat = re.compile(r'\bpipeline\s*\(')

    for one_indexed_line, line in enumerate(lines, start=1):
        for pattern, node_type, use_group_label in [
            (source_pat, "input", True),
            (op_pat, "operator", True),
            (pipeline_pat, "pipeline", False),
        ]:
            for m in pattern.finditer(line):
                start_col = m.start() + 1  # 1-based
                end_col = m.end()  # 1-based inclusive-ish
                if node_type == "input":
                    label = m.group(1) if m.lastindex else "input"
                    node_id = f"input_{label}"
                elif node_type == "operator":
                    label = m.group(1) if m.lastindex else "op"
                    node_id = f"op_{label}_{one_indexed_line}"
                else:
                    label = "Pipeline"
                    node_id = f"pipeline_{one_indexed_line}"
                results.append(
                    (one_indexed_line, start_col, one_indexed_line, end_col, node_id, node_type, label)
                )
    return results


def extract_nodes_with_ranges(input_code: str) -> list[CompileNode]:
    """Parse pipeline source and return graph nodes with source ranges for decorations and code–graph sync."""
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
    return nodes
