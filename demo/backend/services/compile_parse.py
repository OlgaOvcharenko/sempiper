"""
Extract sempipe-like elements from pipeline source for code–graph mapping (static preview).
Inspired by sempipes/demo.ipynb: as_X, as_y, sem_fillna, sem_gen_features,
skb.apply, apply_with_sem_choose, sem_choose, skb.eval. Also supports legacy source/op/pipeline.
Uses simple regex/line scan; does not depend on sempipes.

The static graph is a DAG that reflects data flow: edges go from the node that
produces a variable to the node that consumes it (not document order).
"""

import re
from typing import NamedTuple

from models.schemas import CompileEdge, CompileNode, SourceRange


class _RawEntry(NamedTuple):
    """Parsed pipeline call: (start_line, start_col, end_line, end_col, node_id, node_type, label)."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int
    node_id: str
    node_type: str
    label: str


def _line_at(lines: list[str], one_indexed_line: int) -> str:
    """Return line at 1-based index, or empty string if out of range."""
    return lines[one_indexed_line - 1] if 1 <= one_indexed_line <= len(lines) else ""


def _line_context(lines: list[str], start_line: int, extra_lines: int = 4) -> str:
    """Return lines from start_line (1-based) for multi-line context."""
    if start_line < 1 or start_line > len(lines):
        return ""
    end = min(start_line + extra_lines, len(lines) + 1)
    return "\n".join(lines[start_line - 1 : end])

# Patterns for "this line contains a pipeline node" (used to skip when building depends_on)
_NODE_PATTERNS = (
    r"skrub\.var\s*\(",
    r"\.skb\.subsample\s*\(",
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


def _find_call_ranges(text: str) -> list[_RawEntry]:
    """Find sempipe-style calls. Returns list of _RawEntry."""
    results: list[_RawEntry] = []
    lines = text.split("\n")

    skrub_var_pat = re.compile(r"skrub\.var\s*\(")
    skb_subsample_pat = re.compile(r"\.skb\.subsample\s*\(")
    as_x_pat = re.compile(r"\bas_X\s*\(")
    as_y_pat = re.compile(r"\bas_y\s*\(")
    sem_fillna_pat = re.compile(r"\.sem_fillna\s*\(")
    sem_gen_features_pat = re.compile(r"\.sem_gen_features\s*\(")
    apply_with_sem_choose_pat = re.compile(r"\.skb\.apply_with_sem_choose\s*\(")
    skb_apply_pat = re.compile(r"\.skb\.apply\s*\(")
    skb_eval_pat = re.compile(r"\.skb\.eval\s*\(")
    sem_choose_pat = re.compile(r"\bsem_choose\s*\(")
    source_pat = re.compile(r'\bsource\s*\(\s*["\']([^"\']*)["\']\s*\)')
    op_pat = re.compile(r'\bop\s*\(\s*["\']([^"\']*)["\']\s*\)')
    pipeline_pat = re.compile(r"\bpipeline\s*\(")

    def add(line_no: int, start: int, end: int, node_id: str, node_type: str, label: str) -> None:
        # Both start and end are 0-indexed from regex match; convert to 1-indexed for Monaco
        results.append(_RawEntry(line_no, start + 1, line_no, end + 1, node_id, node_type, label))

    for one_indexed_line, line in enumerate(lines, start=1):
        # Only match in code; ignore content after first # (line comment)
        comment_start = line.find("#")
        search_line = line[:comment_start] if comment_start >= 0 else line
        for m in skrub_var_pat.finditer(search_line):
            # skrub.var("name", ...) or skrub.var('name', ...) -> capture name
            name_match = re.search(r'skrub\.var\s*\(\s*["\']([^"\']*)["\']', search_line[m.start() :])
            label = name_match.group(1) if name_match else "var"
            add(one_indexed_line, m.start(), m.end(), f"var_{label}_{one_indexed_line}", "input", label)
        for m in skb_subsample_pat.finditer(search_line):
            # products.skb.subsample -> receiver is "products"
            rec_match = re.search(r"(\w+)\.skb\.subsample", search_line[: m.end()])
            label = rec_match.group(1) if rec_match else "subsample"
            add(one_indexed_line, m.start(), m.end(), f"subsample_{one_indexed_line}", "operator", f"skb.subsample")
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
    apply_with_sem_choose, the y= argument. For as_X/as_y, the first argument (e.g. baskets).
    """
    left = line[: call_start + 1]
    lhs_match = re.search(r"(\w+)\s*=\s*[^=]*$", left)
    produces = lhs_match.group(1) if lhs_match else None

    consumes: list[str] = []
    if node_label in ("as_X", "as_y"):
        # First argument: as_X(baskets[["ID"]], ...) or as_y(baskets["fraud_flag"], ...) -> consumes baskets
        # Search line_context when multi-line (e.g. as_X(\n    baskets[...])
        search_text = (line_context or line)
        first_arg_match = re.search(r"(?:as_X|as_y)\s*\(\s*(\w+)", search_text)
        if first_arg_match:
            consumes.append(first_arg_match.group(1))
        return produces, consumes
    # Method call: search full line for (\w+)\.(sem_fillna|...|skb.eval|skb.subsample)
    receiver_match = re.search(
        r"(\w+)\.(?:sem_fillna|sem_gen_features|skb\.apply(?:_with_sem_choose)?|skb\.eval|skb\.subsample)\s*\(", line
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


def _add_edge(
    edges: list[CompileEdge],
    seen: set[tuple[str, str]],
    source: str,
    target: str,
) -> None:
    """Add edge if not already present."""
    if source != target and (source, target) not in seen:
        seen.add((source, target))
        edges.append(CompileEdge(source=source, target=target))


def _infer_edges_from_flow(raw: list[_RawEntry], lines: list[str]) -> list[CompileEdge]:
    """
    Infer DAG edges from data flow: who produces a var and who consumes it.
    Build var_producer in document order; resolve consumes for each node; ensure
    as_X/as_y get edges from subsample; add sem_choose -> apply_with_sem_choose.
    """
    depends_on = _build_depends_on(lines)
    var_producer: dict[str, str] = {}
    edges: list[CompileEdge] = []
    seen: set[tuple[str, str]] = set()

    # Pass 1: data flow (produces/consumes)
    for r in raw:
        line = _line_at(lines, r.start_line)
        ctx = _line_context(lines, r.start_line)
        produces, consumes_list = _extract_produces_consumes(
            line, r.label, r.node_type, r.start_col - 1, line_context=ctx
        )
        for var in consumes_list:
            for src_id in _resolve_producers(var, var_producer, depends_on, set()):
                _add_edge(edges, seen, src_id, r.node_id)
        if produces:
            var_producer[produces] = r.node_id

    # Pass 2: ensure as_X/as_y have edges from subsample (explicit handling)
    # Use _resolve_producers to follow full dependency chain; use line_context for multi-line calls
    for r in raw:
        if r.label not in ("as_X", "as_y"):
            continue
        line = _line_at(lines, r.start_line)
        ctx = _line_context(lines, r.start_line)
        _, consumes_list = _extract_produces_consumes(
            line, r.label, r.node_type, r.start_col - 1, line_context=ctx
        )
        for var in consumes_list:
            for src_id in _resolve_producers(var, var_producer, depends_on, set()):
                if src_id == r.node_id:
                    continue
                src_entry = next((x for x in raw if x.node_id == src_id), None)
                if src_entry and src_entry.label == "skb.subsample":
                    _add_edge(edges, seen, src_id, r.node_id)
                    break
            else:
                continue
            break

    # sem_choose -> apply_with_sem_choose (choices= parameter)
    apply_nodes = [(r.start_line, r.node_id) for r in raw if r.label == "apply_with_sem_choose"]
    for r in raw:
        if r.label != "sem_choose" or not apply_nodes:
            continue
        containing = [(sl, nid) for sl, nid in apply_nodes if sl < r.start_line]
        if containing:
            _, apply_id = max(containing, key=lambda x: x[0])
            _add_edge(edges, seen, r.node_id, apply_id)

    return edges


def extract_nodes_with_ranges(input_code: str) -> tuple[list[CompileNode], list[CompileEdge]]:
    """Parse pipeline source and return graph nodes (with source ranges) and DAG edges from data flow."""
    raw = _find_call_ranges(input_code)
    lines = input_code.split("\n")
    seen: set[str] = set()
    nodes: list[CompileNode] = []
    for r in raw:
        if r.node_id in seen:
            continue
        seen.add(r.node_id)
        nodes.append(
            CompileNode(
                id=r.node_id,
                type=r.node_type,
                label=r.label,
                source_range=SourceRange(
                    start_line=r.start_line,
                    start_column=r.start_col,
                    end_line=r.end_line,
                    end_column=r.end_col,
                ),
            )
        )
    if not nodes:
        # Return empty graph - frontend shows "No computation graph yet"
        return [], []

    edges = _infer_edges_from_flow(raw, lines)
    # Fallback: if data flow yields no edges (e.g. snippet without assignments), use document order
    if not edges and len(nodes) > 1:
        edges = [
            CompileEdge(source=nodes[i].id, target=nodes[i + 1].id)
            for i in range(len(nodes) - 1)
        ]
    return nodes, edges
