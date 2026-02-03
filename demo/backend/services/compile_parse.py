"""
Extract sempipe-like elements from pipeline source for code–graph mapping.
Inspired by sempipes/demo.ipynb: as_X, as_y, sem_fillna, sem_gen_features,
skb.apply, apply_with_sem_choose, sem_choose, skb.eval. Also supports legacy source/op/pipeline.
Uses simple regex/line scan; does not depend on sempipes. For production,
the scrub compiler could provide precise ranges.

The graph is a DAG that reflects data flow: edges go from the node that
produces a variable to the node that consumes it (not document order).
When a sink DataOp is available (e.g. after executing the script), skrub
provides the authoritative graph:
  - DataOp.skb.draw_graph() → SVG/PNG (GraphDrawing with .svg, .png, .open())
    https://skrub-data.org/stable/reference/generated/skrub.DataOp.skb.draw_graph.html
  - DataOp.skb.describe_steps() → text representation (one step per line)
    https://skrub-data.org/stable/reference/generated/skrub.DataOp.skb.describe_steps.html
This module is a best-effort static approximation when no sink DataOp exists.
"""

import re

from models.schemas import CompileEdge, CompileNode, SourceRange

# Patterns for "this line contains a pipeline node" (used to skip when building depends_on)
_NODE_PATTERNS = (
    r"sempipes\.as_X\s*\(",
    r"sempipes\.as_y\s*\(",
    r"\.sem_fillna\s*\(",
    r"\.sem_gen_features\s*\(",
    r"\.skb\.apply\s*\(",
    r"\.skb\.apply_with_sem_choose\s*\(",
    r"\.skb\.eval\s*\(",
    r"\bsem_choose\s*\(",
    r"\bsource\s*\(",
    r"\bop\s*\(",
    r"\bpipeline\s*\(",
)
_HAS_NODE_RE = re.compile("|".join(f"({p})" for p in _NODE_PATTERNS))

_PY_KEYWORDS = frozenset(
    {"and", "or", "not", "in", "is", "True", "False", "None", "if", "else", "for", "while", "def", "class", "import", "from", "return", "with", "as", "try", "except", "lambda", "yield"}
)


def _find_call_ranges(text: str) -> list[tuple[int, int, int, int, str, str, str]]:
    """Find sempipe-style calls. Returns (start_line, start_col, end_line, end_col, node_id, type, label)."""
    results: list[tuple[int, int, int, int, str, str, str]] = []
    lines = text.split("\n")

    as_x_pat = re.compile(r"\bas_X\s*\(")
    as_y_pat = re.compile(r"\bas_y\s*\(")
    sem_fillna_pat = re.compile(r"\.sem_fillna\s*\(")
    sem_gen_features_pat = re.compile(r"\.sem_gen_features\s*\(")
    # Match apply_with_sem_choose before skb.apply (longer pattern first)
    apply_with_sem_choose_pat = re.compile(r"\.skb\.apply_with_sem_choose\s*\(")
    skb_apply_pat = re.compile(r"\.skb\.apply\s*\(")
    skb_eval_pat = re.compile(r"\.skb\.eval\s*\(")
    sem_choose_pat = re.compile(r"\bsem_choose\s*\(")
    source_pat = re.compile(r'\bsource\s*\(\s*["\']([^"\']*)["\']\s*\)')
    op_pat = re.compile(r'\bop\s*\(\s*["\']([^"\']*)["\']\s*\)')
    pipeline_pat = re.compile(r"\bpipeline\s*\(")

    def add(line_no: int, start: int, end: int, node_id: str, node_type: str, label: str) -> None:
        results.append((line_no, start + 1, line_no, end, node_id, node_type, label))

    for one_indexed_line, line in enumerate(lines, start=1):
        # Only match in code; ignore content after first # (line comment)
        comment_start = line.find("#")
        search_line = line[:comment_start] if comment_start >= 0 else line
        for m in as_x_pat.finditer(search_line):
            add(one_indexed_line, m.start(), m.end(), f"as_X_{one_indexed_line}", "input", "as_X")
        for m in as_y_pat.finditer(search_line):
            add(one_indexed_line, m.start(), m.end(), f"as_y_{one_indexed_line}", "input", "as_y")
        for m in sem_fillna_pat.finditer(search_line):
            add(one_indexed_line, m.start(), m.end(), f"sem_fillna_{one_indexed_line}", "operator", "sem_fillna")
        for m in sem_gen_features_pat.finditer(search_line):
            add(
                one_indexed_line,
                m.start(),
                m.end(),
                f"sem_gen_features_{one_indexed_line}",
                "operator",
                "sem_gen_features",
            )
        for m in apply_with_sem_choose_pat.finditer(search_line):
            add(
                one_indexed_line,
                m.start(),
                m.end(),
                f"apply_with_sem_choose_{one_indexed_line}",
                "operator",
                "apply_with_sem_choose",
            )
        for m in skb_apply_pat.finditer(search_line):
            add(one_indexed_line, m.start(), m.end(), f"skb_apply_{one_indexed_line}", "operator", "skb.apply")
        for m in skb_eval_pat.finditer(search_line):
            add(one_indexed_line, m.start(), m.end(), f"skb_eval_{one_indexed_line}", "operator", "skb.eval")
        for m in sem_choose_pat.finditer(search_line):
            add(one_indexed_line, m.start(), m.end(), f"sem_choose_{one_indexed_line}", "operator", "sem_choose")
        for m in source_pat.finditer(search_line):
            label = m.group(1) if m.lastindex else "input"
            add(one_indexed_line, m.start(), m.end(), f"input_{label}", "input", label)
        for m in op_pat.finditer(search_line):
            label = m.group(1) if m.lastindex else "op"
            add(one_indexed_line, m.start(), m.end(), f"op_{label}_{one_indexed_line}", "operator", label)
        for m in pipeline_pat.finditer(search_line):
            add(one_indexed_line, m.start(), m.end(), f"pipeline_{one_indexed_line}", "pipeline", "Pipeline")

    return results


def _extract_produces_consumes(
    line: str, node_label: str, node_type: str, call_start: int, line_context: str | None = None
) -> tuple[str | None, list[str]]:
    """
    From the line containing a pipeline call, extract (produces_var, consumes_vars).
    produces_var: LHS of assignment (e.g. basket_ids in "basket_ids = sempipes.as_X(...)").
    consumes_vars: receiver before the dot (e.g. products in "products.sem_fillna") and, for
    apply_with_sem_choose, the y= argument.
    """
    left = line[: call_start + 1]
    lhs_match = re.search(r"(\w+)\s*=\s*[^=]*$", left)
    produces = lhs_match.group(1) if lhs_match else None

    consumes: list[str] = []
    if node_label in ("as_X", "as_y"):
        return produces, consumes
    # Method call: search full line for (\w+)\.(sem_fillna|...|skb.eval)
    receiver_match = re.search(
        r"(\w+)\.(?:sem_fillna|sem_gen_features|skb\.apply(?:_with_sem_choose)?|skb\.eval)\s*\(", line
    )
    if receiver_match:
        consumes.append(receiver_match.group(1))
    if node_label == "apply_with_sem_choose":
        # y= may be on same line or next few lines (multi-line call)
        search_text = (line_context or line)
        y_match = re.search(r"\by\s*=\s*(\w+)", search_text)
        if y_match and y_match.group(1) not in consumes:
            consumes.append(y_match.group(1))
    return produces, consumes


def _rhs_identifiers(rhs: str) -> list[str]:
    """Extract identifier tokens from RHS of assignment (exclude keywords)."""
    tokens = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", rhs)
    return [t for t in tokens if t not in _PY_KEYWORDS]


def _build_depends_on(lines: list[str]) -> dict[str, list[str]]:
    """
    For lines that assign a var from an expression with no pipeline call, record
    depends_on[lhs] = list of vars from RHS that are "known" (assigned earlier).
    """
    depends_on: dict[str, list[str]] = {}
    known: set[str] = set()
    for line in lines:
        if _HAS_NODE_RE.search(line):
            # This line has a node; LHS will be added to known when we process nodes
            match = re.match(r"^\s*(\w+)\s*=", line)
            if match:
                known.add(match.group(1))
            continue
        match = re.match(r"^\s*(\w+)\s*=\s*(.+)$", line)
        if not match:
            continue
        lhs, rhs = match.group(1), match.group(2)
        ids_in_rhs = _rhs_identifiers(rhs)
        deps = [v for v in ids_in_rhs if v in known]
        if deps:
            depends_on[lhs] = list(dict.fromkeys(deps))
        known.add(lhs)
    return depends_on


def _resolve_producers(
    var: str,
    var_producer: dict[str, str],
    depends_on: dict[str, list[str]],
    visited: set[str],
) -> list[str]:
    """Return list of node_ids that ultimately produce this var (no duplicates, order preserved)."""
    if var in visited:
        return []
    visited.add(var)
    if var in var_producer:
        return [var_producer[var]]
    if var in depends_on:
        out: list[str] = []
        for v in depends_on[var]:
            out.extend(_resolve_producers(v, var_producer, depends_on, visited))
        return list(dict.fromkeys(out))
    return []


def _infer_edges_from_flow(
    raw: list[tuple[int, int, int, int, str, str, str]],
    lines: list[str],
) -> list[CompileEdge]:
    """
    Infer DAG edges from data flow: who produces a var and who consumes it.
    """
    depends_on = _build_depends_on(lines)
    var_producer: dict[str, str] = {}
    edges: list[CompileEdge] = []
    seen_edges: set[tuple[str, str]] = set()

    for start_line, start_col, end_line, end_col, node_id, node_type, label in raw:
        line = lines[start_line - 1] if start_line <= len(lines) else ""
        # Multi-line context for y= in apply_with_sem_choose
        line_context = "\n".join(lines[start_line - 1 : start_line + 4]) if start_line <= len(lines) else line
        produces, consumes_list = _extract_produces_consumes(
            line, label, node_type, start_col - 1, line_context=line_context
        )
        # Resolve consumes before recording this node as producer (so we don't self-reference)
        for c in consumes_list:
            for src_id in _resolve_producers(c, var_producer, depends_on, set()):
                if src_id != node_id and (src_id, node_id) not in seen_edges:
                    seen_edges.add((src_id, node_id))
                    edges.append(CompileEdge(source=src_id, target=node_id))
        if produces:
            var_producer[produces] = node_id

    return edges


def extract_nodes_with_ranges(input_code: str) -> tuple[list[CompileNode], list[CompileEdge]]:
    """Parse pipeline source and return graph nodes (with source ranges) and DAG edges from data flow."""
    raw = _find_call_ranges(input_code)
    lines = input_code.split("\n")
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
    if not nodes:
        nodes = [
            CompileNode(id="input", type="input", label="Input", source_range=None),
            CompileNode(id="op1", type="operator", label="Op", source_range=None),
        ]
        edges = [CompileEdge(source="input", target="op1")]
    else:
        edges = _infer_edges_from_flow(raw, lines)
        # Fallback: if data flow yields no edges (e.g. snippet without assignments), use document order
        if not edges and len(nodes) > 1:
            edges = [
                CompileEdge(source=nodes[i].id, target=nodes[i + 1].id)
                for i in range(len(nodes) - 1)
            ]
    return nodes, edges
