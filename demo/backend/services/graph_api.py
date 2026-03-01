"""
Narrow API for computational graph extraction from pipeline scripts.

This module provides clean entry points for converting a pipeline
script (Python source code) into a computational graph (nodes + edges).

Two modes of operation:
1. Static parsing (compile_script_to_graph): Fast regex-based extraction without execution
2. Dynamic extraction (extract_skrub_graph): Executes rewritten script to get real skrub graph

Usage:
    from services.graph_api import compile_script_to_graph, extract_skrub_graph

    # Static parsing (fast, no execution)
    result = compile_script_to_graph(script_code)

    # Dynamic extraction (executes rewritten script, gets real skrub graph)
    skrub_result = extract_skrub_graph(script_code)
"""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field

from models.schemas import CompileEdge, CompileNode, SourceRange
from services.compile_parse import extract_nodes_with_ranges
from services.graph_validate import validate_graph_json


@dataclass
class GraphResult:
    """Result of compiling a script to a computational graph (static parsing)."""

    nodes: list[CompileNode]
    edges: list[CompileEdge]
    validation_errors: list[str]

    @property
    def is_valid(self) -> bool:
        """True if the graph has no validation errors."""
        return len(self.validation_errors) == 0


@dataclass
class SkrubNode:
    """A node in the skrub computation graph."""

    id: str
    label: str
    is_sempipes_semantic: bool = False


 


def _infer_node_type(label: str, is_sempipes_semantic: bool) -> str:
    """Infer node type from label and semantic flag."""
    if not label:
        return "operator"
    low = label.strip().lower()
    # Input types - check for var-like labels (including raw skrub <Var 'name'>)
    if low in ("var", "as_x", "as_y"):
        return "input"
    if low.startswith("var '") or low.startswith("<var"):
        return "input"
    # Operators
    if is_sempipes_semantic or low.startswith("sem_") or low.startswith("apply") or low.startswith("<apply"):
        return "operator"
    if low in ("skb.subsample", "subsample", "skb.apply", "skb.eval"):
        return "operator"
    if "subsample" in low:  # Handle raw skrub <SubsamplePreviews>
        return "operator"
    # Pandas DataFrame operations
    if low in ("groupby", "merge", "drop"):
        return "operator"
    # Default to operator for unknown
    return "operator"


@dataclass
class SkrubGraphResult:
    """Result of extracting the real skrub computation graph."""

    nodes: list[SkrubNode]
    parents: dict[str, list[str]]  # node_id -> list of parent node_ids
    children: dict[str, list[str]]  # node_id -> list of child node_ids
    rewritten_script: str  # The script that was executed
    error: str | None = None  # Error message if extraction failed
    raw_graph: dict = field(default_factory=dict)  # Raw graph dict from skrub
    svg: str | None = None  # Native skrub SVG (from draw_graph)

    @property
    def is_valid(self) -> bool:
        """True if graph was extracted successfully."""
        return self.error is None and len(self.nodes) > 0

    def to_edges(self) -> list[tuple[str, str]]:
        """Convert parents to edge tuples (source, target) in data flow direction.

        Skrub's parents dict: parents[A] = [B] means B wraps/depends on A.
        In data flow terms: A produces data that B consumes, so edge is A → B.
        """
        edges = []
        for node_id, parent_ids in self.parents.items():
            for parent_id in parent_ids:
                # node_id is upstream (data source), parent_id is downstream (data consumer)
                edges.append((node_id, parent_id))
        return edges

    def to_compile_nodes(self) -> list[CompileNode]:
        """Convert to frontend-compatible CompileNode list."""
        return [
            CompileNode(
                id=node.id,
                type=_infer_node_type(node.label, node.is_sempipes_semantic),
                label=node.label,
                source_range=None,  # Dynamic extraction doesn't provide source ranges
            )
            for node in self.nodes
        ]

    def to_compile_edges(self) -> list[CompileEdge]:
        """Convert parents dict to frontend-compatible CompileEdge list (data flow direction).

        Skrub's parents dict: parents[A] = [B] means B wraps/depends on A.
        In data flow terms: A produces data that B consumes, so edge is A → B.
        """
        edges = []
        seen = set()
        for node_id, parent_ids in self.parents.items():
            for parent_id in parent_ids:
                # node_id is upstream (data source), parent_id is downstream (data consumer)
                if (node_id, parent_id) not in seen:
                    seen.add((node_id, parent_id))
                    edges.append(CompileEdge(source=node_id, target=parent_id))
        return edges

    def to_graph_result(self) -> GraphResult:
        """Convert to frontend-compatible GraphResult."""
        if not self.is_valid:
            # Return empty graph on error - frontend shows "No computation graph yet"
            return GraphResult(
                nodes=[],
                edges=[],
                validation_errors=[self.error] if self.error else [],
            )

        nodes = self.to_compile_nodes()
        edges = self.to_compile_edges()

        # Validate
        _, errors = validate_graph_json(
            [n.model_dump() for n in nodes],
            [e.model_dump() for e in edges],
        )

        return GraphResult(nodes=nodes, edges=edges, validation_errors=errors)


# --- Graph extraction LLM mocks (avoid real LLM during extract_skrub_graph) ---

_SEM_CHOOSE_MOCK_CONTENT = "__generated_sempipes_choices = skrub.choose_from([5, 3, 7, 10])"


def _graph_extraction_mock_completion(*args: object, **kwargs: object) -> object:
    """Return a litellm-style response so sem_choose/apply_with_sem_choose run without calling the real LLM.

    Sempipes reads response.choices[0].message["content"] and safe_exec's it. This content must be
    valid Python that defines __generated_sempipes_choices (e.g. via skrub.choose_from(...)).
    """
    return _GraphExtractionMockResponse(_SEM_CHOOSE_MOCK_CONTENT)


def _graph_extraction_mock_batch_completion(*args: object, messages: list | None = None, **kwargs: object) -> list:
    """Return a list of litellm-style responses for batch_completion (one per message)."""
    n = len(messages) if messages else 1
    return [_GraphExtractionMockResponse(_SEM_CHOOSE_MOCK_CONTENT) for _ in range(n)]


class _GraphExtractionMockResponse:
    """Minimal object satisfying response.choices[0].message['content']."""

    def __init__(self, content: str) -> None:
        self.choices = [_GraphExtractionMockChoice(content)]


class _GraphExtractionMockChoice:
    def __init__(self, content: str) -> None:
        self.message = {"content": content}


def compile_script_to_graph(script: str) -> GraphResult:
    """
    Compile a pipeline script to a computational graph using static parsing.

    This is fast regex-based extraction that does NOT execute the script.

    Args:
        script: Python source code containing pipeline declarations.

    Returns:
        GraphResult with nodes, edges, and validation_errors.
    """
    nodes, edges = extract_nodes_with_ranges(script)

    _, errors = validate_graph_json(
        [n.model_dump() for n in nodes],
        [e.model_dump() for e in edges],
    )

    return GraphResult(nodes=nodes, edges=edges, validation_errors=errors)


# --- Script Rewriting ---
#
# Preprocessing step for graph extraction: rewrite skrub.var() so the data
# argument is removed and the dataset part is not evaluated, e.g.:
#
#   products = skrub.var("products", dataset.products)
#   ->  products = skrub.var("products")
#


def _rewrite_var_calls(script: str) -> str:
    """
    Rewrite skrub.var() calls to remove data arguments.

    Transforms:
        products = skrub.var("products", dataset.products)
    To:
        products = skrub.var("products")

    This allows the script to build the computation graph without
    requiring actual data or triggering eager execution.
    """
    # Pattern matches skrub.var("name", <anything>) or skrub.var('name', <anything>)
    # We need to handle nested parentheses in the second argument
    lines = script.split('\n')
    result_lines = []

    for line in lines:
        # Check if line contains skrub.var with two arguments
        # Match: skrub.var("name", ...) or skrub.var('name', ...)
        var_match = re.search(r'(skrub\.var\s*\(\s*["\'])([^"\']+)(["\'])\s*,', line)
        if var_match:
            # Find the matching closing parenthesis for the var call
            start_idx = var_match.start()
            paren_start = line.find('(', start_idx)
            if paren_start != -1:
                # Count parentheses to find the matching close
                depth = 1
                idx = paren_start + 1
                while idx < len(line) and depth > 0:
                    if line[idx] == '(':
                        depth += 1
                    elif line[idx] == ')':
                        depth -= 1
                    idx += 1
                if depth == 0:
                    # Replace the var call with just the name argument
                    name = var_match.group(2)
                    quote = var_match.group(3)
                    prefix = line[:start_idx]
                    suffix = line[idx:]
                    new_var_call = f'skrub.var({quote}{name}{quote})'
                    line = prefix + new_var_call + suffix
        result_lines.append(line)

    return '\n'.join(result_lines)


def _remove_eval_calls(script: str) -> str:
    """
    Remove or comment out .skb.eval() calls from the script.

    The eval() call triggers execution which we want to avoid.
    Instead, we'll extract the graph from the DataOp before eval.
    """
    # Pattern matches: something.skb.eval() or .skb.eval(...)
    # We want to remove the .skb.eval() part but keep the variable assignment
    lines = script.split('\n')
    result_lines = []

    for line in lines:
        # Check if line has .skb.eval()
        if '.skb.eval(' in line:
            # Find assignment pattern: result = something.skb.eval()
            assign_match = re.match(r'^(\s*)(\w+)\s*=\s*(.+)\.skb\.eval\s*\([^)]*\)\s*$', line)
            if assign_match:
                indent = assign_match.group(1)
                var_name = assign_match.group(2)
                data_op = assign_match.group(3)
                # Replace with assignment to the DataOp (without eval)
                line = f'{indent}{var_name} = {data_op}'
            else:
                # Just comment out standalone eval calls
                line = '# ' + line + '  # eval removed for graph extraction'
        result_lines.append(line)

    return '\n'.join(result_lines)


def _remove_skrub_datasets_fetches(script: str) -> str:
    """
    Remove skrub.datasets.fetch_*() calls so we don't run them during graph extraction.

    Transforms: dataset = skrub.datasets.fetch_credit_fraud()  ->  dataset = None
    Combined with var rewrite, nothing in the script needs the dataset for building the graph.
    """
    lines = script.split("\n")
    result_lines = []
    fetch_pat = re.compile(
        r"^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*skrub\.datasets\.fetch_\w+\s*\([^)]*\)\s*$"
    )
    for line in lines:
        m = fetch_pat.match(line)
        if m:
            indent, var = m.group(1, 2)
            line = f"{indent}{var} = None  # skrub.datasets fetch removed for graph extraction"
        result_lines.append(line)
    return "\n".join(result_lines)


def _remove_cross_validate_calls(script: str) -> str:
    """
    Replace .skb.cross_validate(...) with the DataOp so we don't run CV during graph extraction.

    Transforms: res = expr.skb.cross_validate(cv=2)  ->  res = expr
    """
    lines = script.split("\n")
    result_lines = []
    for line in lines:
        if ".skb.cross_validate(" in line:
            # Match: var = something.skb.cross_validate(...)
            assign_match = re.match(
                r"^(\s*)(\w+)\s*=\s*(.+)\.skb\.cross_validate\s*\([^)]*\)\s*$",
                line,
            )
            if assign_match:
                indent, var_name, data_op = assign_match.group(1, 2, 3)
                line = f"{indent}{var_name} = {data_op}"
        result_lines.append(line)
    return "\n".join(result_lines)


def _remove_optimise_colopro_calls(script: str) -> str:
    """
    Remove optimise_colopro calls and replace with assignment to dag_sink.

    Transforms:
        outcomes = optimise_colopro(dag_sink=pipeline, ...)
    To:
        outcomes = pipeline
    """
    lines = script.split('\n')
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.search(r"^(\s*)(\w+)\s*=\s*optimise_colopro\s*\(", line)
        if match:
            indent, var_name = match.group(1), match.group(2)
            # Find the dag_sink argument in this or subsequent lines
            dag_sink_var = None
            j = i
            call_content = ""
            while j < len(lines):
                call_content += lines[j]
                if ')' in lines[j]:
                    break
                j += 1

            # Simple regex check for dag_sink=var
            sink_match = re.search(r"dag_sink\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)", call_content)
            if sink_match:
                dag_sink_var = sink_match.group(1)
            else:
                # Assuming first positional arg is dag_sink
                args_content = call_content[call_content.find('(') + 1:]
                first_arg = args_content.split(',')[0].strip()
                if first_arg and first_arg.isidentifier():
                    dag_sink_var = first_arg

            if dag_sink_var:
                result_lines.append(f"{indent}{var_name} = {dag_sink_var}  # optimise_colopro stripped")
                i = j + 1
                continue

        result_lines.append(line)
        i += 1
    return '\n'.join(result_lines)


def _strip_pipeline_runner(script: str) -> str:
    """Strip the runner boilerplate from scripts following the sempipes_pipeline() pattern.

    Scripts that wrap the pipeline in a function (like fraud.py, and the new simple/medium.py)
    have a "# Load dataset" marker followed by runner code that should not be executed during
    graph extraction. This function strips that runner and replaces it with a direct call to
    the pipeline function so the DataOp is available in globals.

    Example transformation:
        def sempipes_pipeline():
            ...
            return fraud_detector

        # Load dataset
        dataset = skrub.datasets.fetch_credit_fraud()
        ...

    Becomes:
        def sempipes_pipeline():
            ...
            return fraud_detector

        graph_result = sempipes_pipeline()
    """
    lines = script.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == "# Load dataset":
            body = "".join(lines[:i])
            fn_match = re.search(r"^def\s+(\w+)\s*\(\s*\)\s*:", body, re.MULTILINE)
            if fn_match:
                fn_name = fn_match.group(1)
                return body + f"\ngraph_result = {fn_name}()\n"
            return body
    return script


def rewrite_script_for_graph_extraction(script: str) -> str:
    """
    Rewrite a pipeline script for graph extraction without full execution.

    Preprocessing:
    - Remove skrub.datasets.fetch_*() so we don't run dataset load during exec.
    - Strip the data argument from skrub.var(name, data) -> skrub.var(name), e.g.:
      products = skrub.var("products", dataset.products)  ->  products = skrub.var("products")
    - Strip runner boilerplate (after "# Load dataset") for function-wrapped scripts.

    Transformations:
    1. skrub.datasets.fetch_*(...) -> assign None (preprocessing: no dataset load).
    2. skrub.var("name", data) -> skrub.var("name") (preprocessing: no data argument).
    3. Remove .skb.eval() calls (so we don't materialize the pipeline).
    4. Remove .skb.cross_validate() calls (so we don't run CV; keep the DataOp for graph).
    5. Strip runner boilerplate and add pipeline function call for graph extraction.

    Args:
        script: Original pipeline script

    Returns:
        Rewritten script that can be executed to build the computation graph.
    """
    script = _strip_pipeline_runner(script)
    script = _remove_skrub_datasets_fetches(script)
    script = _rewrite_var_calls(script)
    script = _remove_eval_calls(script)
    script = _remove_cross_validate_calls(script)
    script = _remove_optimise_colopro_calls(script)
    return script


# --- Skrub Graph Extraction ---


def _is_dataop(val) -> bool:
    """Check if a value is a skrub DataOp."""
    try:
        skb = getattr(val, "skb", None)
        if skb is None:
            return False
        draw = getattr(skb, "draw_graph", None)
        return callable(draw)
    except Exception:
        return False


def _get_last_dataop(globals_dict: dict, script: str):
    """Find the last-assigned DataOp in the executed globals."""
    # Get all DataOp names
    dataop_names = set()
    for name, val in globals_dict.items():
        if name.startswith("_"):
            continue
        if _is_dataop(val):
            dataop_names.add(name)

    if not dataop_names:
        return None

    # Find the last assigned variable that is a DataOp
    assign_pat = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=")
    assignments = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        m = assign_pat.match(line)
        if m:
            assignments.append(m.group(1))

    for var_name in reversed(assignments):
        if var_name in dataop_names:
            return globals_dict[var_name]

    return None


def _is_sempipes_semantic_label(label: str) -> bool:
    """Check if a label corresponds to a sempipes semantic operator."""
    if not label or not isinstance(label, str):
        return False
    low = label.strip().lower()
    if low.startswith("sem_"):
        return True
    if low in ("apply_with_sem_choose", "sem_choose", "apply"):
        return True
    if low.startswith("apply ") or low.startswith("<apply "):
        return True
    # Handle raw skrub labels like <Apply LLMImputer>
    if "llmimputer" in low or "learnedimputer" in low or "imputedlearner" in low:
        return True
    if "llmfeaturegenerator" in low or "codebasedfeatureextractor" in low:
        return True
    if "codedataaugmentor" in low or "codeaugmentor" in low:
        return True
    return False


def _extract_svg_from_dataop(data_op) -> str | None:
    """Extract SVG string from DataOp using skb.draw_graph().svg."""
    try:
        graph_obj = data_op.skb.draw_graph()
        if graph_obj is None:
            return None
        svg = getattr(graph_obj, "svg", None)
        if svg is None:
            return None
        return svg.decode("utf-8") if isinstance(svg, bytes) else str(svg)
    except Exception:
        return None


def _graph_to_result(raw: dict, rewritten_script: str) -> SkrubGraphResult:
    """Convert raw skrub graph dict to SkrubGraphResult."""
    nodes_raw = raw.get("nodes") or {}
    parents_raw = raw.get("parents") or {}
    children_raw = raw.get("children") or {}

    # Convert nodes dict to list
    if isinstance(nodes_raw, dict):
        node_items = list(nodes_raw.items())
    else:
        node_items = list(enumerate(nodes_raw))

    nodes = []
    for node_id, node_obj in node_items:
        # Get label from node object
        raw_label = str(node_id)
        if node_obj is not None:
            # Try to get label from skrub's short repr
            try:
                short_repr = getattr(node_obj, "__skrub_short_repr__", None)
                if callable(short_repr):
                    lab = short_repr()
                    if lab and isinstance(lab, str):
                        raw_label = lab[:80]
            except Exception:
                pass
            if raw_label == str(node_id):
                # Fallback to other attributes
                for attr in ("description", "name", "label"):
                    try:
                        v = getattr(node_obj, attr, None)
                        if v and isinstance(v, str):
                            raw_label = v[:80]
                            break
                    except Exception:
                        pass

        # Use raw skrub label without normalization
        label = raw_label

        nodes.append(SkrubNode(
            id=str(node_id),
            label=label,
            is_sempipes_semantic=_is_sempipes_semantic_label(label),
        ))

    # Convert parents and children to string keys
    def to_str_dict(d):
        result = {}
        for k, v in d.items():
            str_key = str(k)
            if isinstance(v, (list, tuple)):
                result[str_key] = [str(x) for x in v]
            else:
                result[str_key] = []
        return result

    return SkrubGraphResult(
        nodes=nodes,
        parents=to_str_dict(parents_raw),
        children=to_str_dict(children_raw),
        rewritten_script=rewritten_script,
        raw_graph=raw,
    )


def extract_skrub_graph(script: str, timings_out: dict[str, float] | None = None) -> SkrubGraphResult:
    """
    Extract the real skrub computation graph by executing a rewritten script.

    This function:
    1. Rewrites the script to remove data arguments and eval calls
    2. Executes the rewritten script to build the computation graph
    3. Extracts the graph structure using skrub's internal graph() function

    Note: Execution runs the full script (e.g. fetch_credit_fraud(), subsample),
    so extraction can be slow for large pipelines. For fast graph-from-code only,
    use compile_script_to_graph (static) instead.

    Args:
        script: Python source code containing pipeline declarations
        timings_out: If provided, filled with rewrite_ms, exec_globals_ms, exec_ms,
            get_last_dataop_ms, skrub_graph_ms (for profiling).

    Returns:
        SkrubGraphResult with nodes, parent/child relationships, and the rewritten script.
        If extraction fails, error will contain the error message.

    Example:
        >>> result = extract_skrub_graph('''
        ... products = skrub.var("products", dataset.products)
        ... products = products.skb.subsample(n=100)
        ... result = products.skb.eval()
        ... ''')
        >>> result.is_valid
        True
        >>> len(result.nodes)
        2
    """
    t0 = time.perf_counter()
    rewritten = rewrite_script_for_graph_extraction(script)
    if timings_out is not None:
        timings_out["rewrite_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    exec_globals = {"__builtins__": __builtins__}

    try:
        import skrub
        exec_globals["skrub"] = skrub
    except ImportError as e:
        if timings_out is not None:
            timings_out["exec_globals_ms"] = (time.perf_counter() - t0) * 1000
        return SkrubGraphResult(
            nodes=[],
            parents={},
            children={},
            rewritten_script=rewritten,
            error=f"skrub not available: {e}",
        )

    try:
        import sempipes
        exec_globals["sempipes"] = sempipes
    except ImportError:
        pass  # sempipes is optional

    try:
        from sempipes import sem_choose
        exec_globals["sem_choose"] = sem_choose
    except ImportError:
        pass

    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        exec_globals["HistGradientBoostingClassifier"] = HistGradientBoostingClassifier
    except ImportError:
        pass

    try:
        from sklearn.linear_model import LinearRegression
        exec_globals["LinearRegression"] = LinearRegression
    except ImportError:
        pass

    try:
        from catboost import CatBoostClassifier
        exec_globals["CatBoostClassifier"] = CatBoostClassifier
    except ImportError:
        pass

    if timings_out is not None:
        timings_out["exec_globals_ms"] = (time.perf_counter() - t0) * 1000

    # Patch sempipes.llm.llm so apply_with_sem_choose does not call the real LLM during graph extraction.
    llm_module = None
    try:
        import sempipes.llm.llm as llm_module
    except ImportError:
        pass
    orig_completion = None
    orig_batch = None
    if llm_module is not None:
        orig_completion = llm_module.completion
        orig_batch = getattr(llm_module, "batch_completion", None)
        llm_module.completion = _graph_extraction_mock_completion
        llm_module.batch_completion = _graph_extraction_mock_batch_completion

    try:
        t0 = time.perf_counter()
        try:
            exec(rewritten, exec_globals)
        except Exception as e:
            if timings_out is not None:
                timings_out["exec_ms"] = (time.perf_counter() - t0) * 1000
            return SkrubGraphResult(
                nodes=[],
                parents={},
                children={},
                rewritten_script=rewritten,
                error=f"Execution failed: {e}",
            )
        if timings_out is not None:
            timings_out["exec_ms"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        data_op = _get_last_dataop(exec_globals, rewritten)
        if timings_out is not None:
            timings_out["get_last_dataop_ms"] = (time.perf_counter() - t0) * 1000
        if data_op is None:
            return SkrubGraphResult(
                nodes=[],
                parents={},
                children={},
                rewritten_script=rewritten,
                error="No DataOp found in executed script",
            )

        t0 = time.perf_counter()
        try:
            from skrub._data_ops._evaluation import graph as skrub_graph
            raw = skrub_graph(data_op)
            if timings_out is not None:
                timings_out["skrub_graph_ms"] = (time.perf_counter() - t0) * 1000
            result = _graph_to_result(raw, rewritten)
            result.svg = _extract_svg_from_dataop(data_op)
            return result
        except ImportError:
            try:
                from skrub._data_ops._evaluation import _Graph
                raw = _Graph().run(data_op)
                if timings_out is not None:
                    timings_out["skrub_graph_ms"] = (time.perf_counter() - t0) * 1000
                result = _graph_to_result(raw, rewritten)
                result.svg = _extract_svg_from_dataop(data_op)
                return result
            except Exception as e:
                if timings_out is not None:
                    timings_out["skrub_graph_ms"] = (time.perf_counter() - t0) * 1000
                return SkrubGraphResult(
                    nodes=[],
                    parents={},
                    children={},
                    rewritten_script=rewritten,
                    error=f"Graph extraction failed: {e}",
                )
        except Exception as e:
            if timings_out is not None:
                timings_out["skrub_graph_ms"] = (time.perf_counter() - t0) * 1000
            return SkrubGraphResult(
                nodes=[],
                parents={},
                children={},
                rewritten_script=rewritten,
                error=f"Graph extraction failed: {e}",
            )
    finally:
        if llm_module is not None:
            llm_module.completion = orig_completion
            if orig_batch is not None:
                llm_module.batch_completion = orig_batch


def _extract_key_from_skrub_label(label: str) -> str:
    """Extract a matching key from a raw skrub label.

    Examples:
        <Var 'products'> -> products
        <SubsamplePreviews> -> skb.subsample
        <Apply LLMFeatureGenerator> -> sem_gen_features
        <GetItem 'col'> -> getitem
    """
    if not label:
        return ""
    low = label.strip().lower()

    # Handle <Var 'name'> -> extract the name
    var_match = re.match(r"<var\s*['\"]([^'\"]+)['\"]>", low)
    if var_match:
        return var_match.group(1)

    # Handle <SubsamplePreviews> -> skb.subsample
    if "subsample" in low:
        return "skb.subsample"

    # Handle <Apply X> patterns (aligned with graph_fusion._OPERATOR_MAPPINGS)
    apply_match = re.match(r"<apply\s+(\w+)>", low)
    if apply_match:
        estimator = apply_match.group(1).lower()
        if estimator in ("learnedimputer", "llmimputer", "imputedlearner", "semfillnawithllm", "semfillnalllmplusmodel"):
            return "sem_fillna"
        if estimator in ("llmfeaturegenerator", "codebasedfeatureextractor", "caafe", "semgenfeaturescaafe"):
            return "sem_gen_features"
        if estimator in ("codedataaugmentor", "directdataaugmentor", "codeaugmentor", "semaugmentdata"):
            return "sem_augment"
        if estimator in ("selectcols", "semselectllm", "filter"):
            return "sem_select"
        if estimator in ("llmcleaner", "semcleanwithllm"):
            return "sem_clean"
        if estimator in ("llmdeduplicator", "semrefinewithllm"):
            return "sem_refine"
        if estimator in ("llmcodegensemaggfeaturesestimator", "llmcodegensemaaggjoinfeaturesoperator", "semaggfeatures"):
            return "sem_agg_features"
        if estimator in ("codedatadistiller", "semdistilldata"):
            return "sem_distill"
        if estimator in ("llmfeatureextractor", "semextractfeaturesllm"):
            return "sem_extract_features"
        if estimator in ("tablevectorizer",):
            return "tablevectorizer"
        if estimator in ("histgradientboostingclassifier", "histgradientboostingregressor", "randomforestclassifier", "randomforestregressor", "gradientboostingclassifier", "gradientboostingregressor", "xgbclassifier", "xgbregressor", "lgbmclassifier", "lgbmregressor"):
            return "apply_with_sem_choose"
        return f"apply_{estimator}"

    # Handle <EvalMode> -> skb.eval
    if low == "<evalmode>":
        return "skb.eval"

    # Handle <GetItem 'x'> -> getitem
    if low.startswith("<getitem"):
        return "getitem"

    # Handle <CallMethod 'name'> -> extract name
    method_match = re.match(r"<callmethod\s*['\"]([^'\"]+)['\"]>", low)
    if method_match:
        return method_match.group(1)

    # Handle <Call 'name'>
    call_match = re.match(r"<call\s*['\"]([^'\"]+)['\"]>", low)
    if call_match:
        return call_match.group(1)

    # Default: use label as-is
    return low


def _extract_column_from_getitem_label(label: str) -> str | None:
    """Extract column name from a GetItem label.

    Examples:
        <GetItem 'col'> -> col
        <GetItem ['col']> -> col
        <GetItem 'basket_ID'> -> basket_ID
        <GetItem ['ID']> -> ID
        <GetItem <CallMethod 'isin'>> -> None (nested, no simple column)
    """
    if not label or not label.startswith("<GetItem"):
        return None

    # Try to extract 'colname' or ['colname']
    # Pattern: <GetItem 'X'> or <GetItem ['X']> or <GetItem ["X"]>
    match = re.search(r"<GetItem\s+\[?['\"]([^'\"]+)['\"]", label)
    if match:
        return match.group(1)
    return None


def _extract_getitem_columns_from_code(code: str, line_number: int) -> set[str]:
    """Extract column names from GetItem operations (df["col"] or df[["col"]]) on a specific line.

    Returns a set of column names found on that line.
    """
    lines = code.splitlines()
    if line_number < 1 or line_number > len(lines):
        return set()

    line = lines[line_number - 1]
    columns = set()

    # Match df["col"] or df[["col", "col2"]]
    # Pattern: [["col"]] or ["col"]
    for match in re.finditer(r'\[+["\']([^"\']+)["\']', line):
        columns.add(match.group(1))

    return columns


def _find_getitem_position_in_line(code: str, line_number: int, column_name: str) -> tuple[int, int] | None:
    """Find the start and end column positions of a GetItem operation for a specific column.

    Captures the variable name and brackets: df["col"] not just ["col"].
    Returns (start_column, end_column) 1-indexed, or None if not found.
    """
    lines = code.splitlines()
    if line_number < 1 or line_number > len(lines):
        return None

    line = lines[line_number - 1]

    # Look for patterns like var[["col"]] or var["col"] with the specific column name
    # We want to capture the variable name and the brackets
    patterns = [
        rf'(\w+\[\["{column_name}"\]\])',  # var[["col"]]
        rf"(\w+\[\['{column_name}'\]\])",  # var[['col']]
        rf'(\w+\["{column_name}"\])',      # var["col"]
        rf"(\w+\['{column_name}'\])",      # var['col']
    ]

    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            start_col = match.start(1) + 1  # +1 for 1-indexed
            end_col = match.end(1)
            return (start_col, end_col)

    return None


def _find_method_call_position(code: str, line_number: int, method_name: str, occurrence: int = 0) -> tuple[int, int] | None:
    """Find the position of a method call (e.g., .agg(), .reset_index()) on a line.

    Returns (start_column, end_column) 1-indexed for the method call, or None if not found.
    occurrence: which occurrence of the method to find (0-indexed).
    """
    lines = code.splitlines()
    if line_number < 1 or line_number > len(lines):
        return None

    line = lines[line_number - 1]

    # Pattern: .method_name(
    pattern = rf'\.{method_name}\s*\('

    matches = list(re.finditer(pattern, line))
    if occurrence < len(matches):
        match = matches[occurrence]
        start_col = match.start() + 1  # +1 for 1-indexed (starts at the dot)
        # End at the opening paren
        end_col = match.end()
        return (start_col, end_col)

    return None


def _merge_source_ranges(
    skrub_nodes: list[CompileNode],
    static_nodes: list[CompileNode],
    script: str,
) -> list[CompileNode]:
    """
    Merge source_range information from static parsing into skrub nodes.

    Matches nodes by extracting keys from raw skrub labels and matching
    against static node labels for code-graph synchronization.

    BUG FIX: Uses a list to track all occurrences of each label, so that
    pipelines with multiple calls to the same operator (e.g., two sem_gen_features)
    can each get their correct source_range.

    Args:
        skrub_nodes: Nodes from dynamic skrub graph extraction (no source ranges yet).
        static_nodes: Nodes from static parsing (have source ranges).
        script: The original source code (used for column name extraction for GetItem matching).
    """
    # Build label -> list of source_ranges mapping from static nodes (in document order)
    # This handles duplicate labels correctly - the Nth occurrence of a label in skrub
    # should match the Nth occurrence in static nodes
    label_to_ranges: dict[str, list] = {}
    for node in static_nodes:
        if node.source_range:
            key = node.label.lower()
            if key not in label_to_ranges:
                label_to_ranges[key] = []
            label_to_ranges[key].append(node.source_range)

    # Extract column names from as_X and as_y lines in the code
    as_x_columns = set()
    as_y_columns = set()
    if "as_x" in label_to_ranges:
        for sr in label_to_ranges["as_x"]:
            as_x_columns.update(_extract_getitem_columns_from_code(script, sr.start_line))
    if "as_y" in label_to_ranges:
        for sr in label_to_ranges["as_y"]:
            as_y_columns.update(_extract_getitem_columns_from_code(script, sr.start_line))

    # Track which occurrence of each label we've used
    label_usage: dict[str, int] = {}

    # Update skrub nodes with source ranges where possible
    result = []
    for node in skrub_nodes:
        source_range = None

        # Try direct match first
        key = node.label.lower()
        if key not in label_to_ranges:
            # Try extracting key from raw skrub label
            key = _extract_key_from_skrub_label(node.label)

        # Special case: GetItem nodes from skrub should match with as_X/as_y from static parse
        # When sempipes.as_X(df[cols]) is called, skrub creates a GetItem node, but static parser
        # creates an as_X node. Map these together ONLY if GetItem hasn't been matched yet.
        # NOTE: We defer GetItem matching until after we try normal label matching, because
        # many GetItem nodes (e.g., df["col"] in filters) should NOT map to as_X/as_y.
        getitem_needs_matching = (key == "getitem")

        # Special case: TableVectorizer maps to skb.apply
        # When skb.apply(TableVectorizer()) is called, skrub creates <Apply TableVectorizer>,
        # but static parse creates skb.apply node.
        # Also handles apply_with_sem_choose from relabeling <Apply MLEstimator>
        # (e.g. skb.apply(HistGradientBoostingClassifier(), y=...)): no direct apply_with_sem_choose
        # in static nodes, so fall back to the next available skb.apply range.
        # Both cases share the same "skb_apply_consumed" counter to avoid double-consuming.
        if key in ("tablevectorizer", "apply_with_sem_choose") and "skb.apply" in label_to_ranges:
            # For apply_with_sem_choose: only fall back to skb.apply when no direct static match
            if key == "apply_with_sem_choose" and "apply_with_sem_choose" in label_to_ranges:
                pass  # Direct match will be handled in the elif below
            else:
                occurrence = label_usage.get("skb_apply_consumed", 0)
                ranges = label_to_ranges["skb.apply"]
                if occurrence < len(ranges):
                    source_range = ranges[occurrence]
                    label_usage["skb_apply_consumed"] = occurrence + 1
                    # Also keep legacy counter for tablevectorizer for backwards compat
                    if key == "tablevectorizer":
                        label_usage["tablevectorizer_to_skb_apply"] = label_usage["skb_apply_consumed"]
                    effective_label = node.label
                    key = f"{key}_matched"
                    getitem_needs_matching = False  # Already matched

        # Special case: Chained pandas methods (agg, reset_index) map to their parent operation
        # e.g., .agg() and .reset_index() after .groupby() should use groupby's LINE,
        # but with corrected CHARACTER positions for the specific method call
        # NOTE: isin is NOT included here because it can appear in filter contexts (not just groupby)
        if key in ("agg", "reset_index", "mean", "sum"):
            # Try to match with groupby first (most common for agg/reset_index)
            if "groupby" in label_to_ranges:
                occurrence = label_usage.get(f"{key}_to_groupby", 0)
                ranges = label_to_ranges["groupby"]
                if occurrence < len(ranges):
                    base_range = ranges[occurrence]
                    # Find the actual character position of this method call on the same line
                    method_pos = _find_method_call_position(script, base_range.start_line, key, occurrence)
                    if method_pos:
                        # Use the method's actual position
                        source_range = SourceRange(
                            start_line=base_range.start_line,
                            start_column=method_pos[0],
                            end_line=base_range.start_line,
                            end_column=method_pos[1],
                        )
                    else:
                        # Fallback to groupby's range if we can't find the method
                        source_range = base_range
                    label_usage[f"{key}_to_groupby"] = occurrence + 1
                    effective_label = node.label
                    key = f"{key}_matched_groupby"
                    getitem_needs_matching = False  # Already matched

        # CodeBasedFeatureExtractor is used by both sem_gen_features and sem_extract_features.
        # Fusion maps it to sem_gen_features. Prefer sem_extract_features when it appears in static
        # (no fallback to sem_gen_features when only sem_extract_features in code). When both
        # appear in static, assign in document order: first skrub node gets sem_extract_features
        # range if available, then sem_gen_features.
        effective_label = node.label
        if key == "sem_gen_features":
            if "sem_extract_features" in label_to_ranges:
                occurrence = label_usage.get("sem_extract_features", 0)
                ranges = label_to_ranges["sem_extract_features"]
                if occurrence < len(ranges):
                    source_range = ranges[occurrence]
                    label_usage["sem_extract_features"] = occurrence + 1
                    effective_label = "sem_extract_features"
                    getitem_needs_matching = False
            if source_range is None and key in label_to_ranges:
                occurrence = label_usage.get(key, 0)
                ranges = label_to_ranges[key]
                if occurrence < len(ranges):
                    source_range = ranges[occurrence]
                    label_usage[key] = occurrence + 1
                    getitem_needs_matching = False
        elif key in label_to_ranges:
            # Get the Nth occurrence of this label's source_range
            occurrence = label_usage.get(key, 0)
            ranges = label_to_ranges[key]
            if occurrence < len(ranges):
                source_range = ranges[occurrence]
                label_usage[key] = occurrence + 1
                getitem_needs_matching = False

        # Deferred GetItem matching: Only match GetItem to as_X/as_y if no other match was found
        # AND the column name in the GetItem matches the expected column for as_X/as_y.
        # This prevents non-as_X/as_y GetItem nodes (e.g., df["col"] in filters) from consuming
        # the as_X/as_y mappings.
        # Also corrects character positions to point to the actual GetItem expression.
        if getitem_needs_matching and source_range is None:
            getitem_col = _extract_column_from_getitem_label(node.label)

            # Try to match with as_X first (if column matches), then as_y
            for candidate_key, candidate_columns in [("as_x", as_x_columns), ("as_y", as_y_columns)]:
                if candidate_key in label_to_ranges:
                    # Only match if the GetItem column is in the expected columns for this as_X/as_y
                    if getitem_col and getitem_col in candidate_columns:
                        occurrence = label_usage.get(f"getitem_to_{candidate_key}", 0)
                        ranges = label_to_ranges[candidate_key]
                        if occurrence < len(ranges):
                            base_range = ranges[occurrence]
                            # Find the actual character position of the GetItem on this line
                            getitem_pos = _find_getitem_position_in_line(script, base_range.start_line, getitem_col)
                            if getitem_pos:
                                # Use the GetItem's actual position
                                source_range = SourceRange(
                                    start_line=base_range.start_line,
                                    start_column=getitem_pos[0],
                                    end_line=base_range.start_line,
                                    end_column=getitem_pos[1],
                                )
                            else:
                                # Fallback to as_X/as_y range if we can't find the GetItem
                                source_range = base_range
                            label_usage[f"getitem_to_{candidate_key}"] = occurrence + 1
                            # Also mark this position as used to prevent other GetItem nodes from using it
                            label_usage[f"getitem_{getitem_col}_line_{base_range.start_line}"] = 1
                            effective_label = node.label  # Keep original GetItem label
                            break

        # Final fallback: For GetItem and CallMethod nodes that still don't have source_range,
        # try to find them in the source code (for intermediate operations like line 27)
        if source_range is None and (key == "getitem" or key in ("isin",)):
            # Extract column name or method name from the label
            if key == "getitem":
                getitem_col = _extract_column_from_getitem_label(node.label)
                if getitem_col:
                    # Search for this GetItem in all lines
                    for line_num in range(1, len(script.splitlines()) + 1):
                        pos = _find_getitem_position_in_line(script, line_num, getitem_col)
                        if pos:
                            # Check if this line hasn't been used for this column yet
                            usage_key = f"getitem_{getitem_col}_line_{line_num}"
                            if label_usage.get(usage_key, 0) == 0:
                                source_range = SourceRange(
                                    start_line=line_num,
                                    start_column=pos[0],
                                    end_line=line_num,
                                    end_column=pos[1],
                                )
                                label_usage[usage_key] = 1
                                break
            elif key == "isin":
                # Search for .isin( in all lines
                for line_num in range(1, len(script.splitlines()) + 1):
                    pos = _find_method_call_position(script, line_num, "isin", 0)
                    if pos:
                        usage_key = f"isin_line_{line_num}"
                        if label_usage.get(usage_key, 0) == 0:
                            source_range = SourceRange(
                                start_line=line_num,
                                start_column=pos[0],
                                end_line=line_num,
                                end_column=pos[1],
                            )
                            label_usage[usage_key] = 1
                            break

        result.append(CompileNode(
            id=node.id,
            type=node.type,
            label=effective_label,
            source_range=source_range,
        ))
    return result


def compile_script_to_graph_dynamic(
    script: str,
    timings_out: dict[str, float] | None = None,
    svg_out: list[str] | None = None,
) -> GraphResult:
    """
    Compile a pipeline script using dynamic extraction (real skrub graph).

    This executes a rewritten version of the script (with data args removed
    and eval calls replaced) to get the actual computation graph from skrub.

    If extraction fails, returns an empty graph (no fallback to static parsing).

    Static parsing runs once for source-range merge (no duplicate compile_script_to_graph).

    Args:
        script: Python source code containing pipeline declarations.
        timings_out: If provided, filled with extract_ms, fuse_ms, static_ms, merge_ms
            (and extract_skrub_graph sub-timings: rewrite_ms, exec_globals_ms, exec_ms,
            get_last_dataop_ms, skrub_graph_ms) for profiling.
        svg_out: If provided (as empty list), the native skrub SVG is appended.

    Returns:
        GraphResult with nodes, edges, and validation_errors.
    """
    # Static parse for source-range pool used in the merge step.
    # Use prune=False so that backslash-continuation nodes (groupby, merge, etc.)
    # that are isolated in the static graph are still available for label-matching
    # against the dynamic (skrub) graph nodes.
    t0 = time.perf_counter()
    static_nodes, _ = extract_nodes_with_ranges(script, prune=False)
    if timings_out is not None:
        timings_out["static_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    skrub_result = extract_skrub_graph(script, timings_out=timings_out)
    if timings_out is not None:
        timings_out["extract_ms"] = (time.perf_counter() - t0) * 1000

    if not skrub_result.is_valid:
        # Fallback to static parsing if dynamic extraction fails
        fallback_result = compile_script_to_graph(script)
        # Append the dynamic error to validation_errors so the user knows why we fell back
        if skrub_result.error:
            fallback_result.validation_errors.append(f"Dynamic extraction failed (falling back to static): {skrub_result.error}")
        return fallback_result

    # Capture SVG if requested
    if svg_out is not None and skrub_result.svg:
        svg_out.append(skrub_result.svg)

    # Get base result from skrub
    result = skrub_result.to_graph_result()

    t0 = time.perf_counter()
    from services.graph_fusion import fuse_graph
    result.nodes, result.edges = fuse_graph(result.nodes, result.edges)
    if timings_out is not None:
        timings_out["fuse_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    if static_nodes:
        result.nodes = _merge_source_ranges(result.nodes, static_nodes, script)
    if timings_out is not None:
        timings_out["merge_ms"] = (time.perf_counter() - t0) * 1000

    return result


_svg_save_logger = logging.getLogger(__name__)


def _extract_single_svg_document(s: str) -> str:
    """Return the first complete SVG document (first <svg to last </svg> inclusive)."""
    start = s.find("<svg")
    if start < 0:
        return s
    end_tag = "</svg>"
    end = s.rfind(end_tag)
    if end < 0 or end < start:
        return s
    return s[start : end + len(end_tag)]


def save_svg_to_cache_async(svg: str | None, cache_key: str | None) -> None:
    """
    Save SVG to cache asynchronously.

    This is called during compile to save the native skrub graph SVG. Runs in a
    background thread to avoid slowing down the compile response.

    Args:
        svg: The SVG string to save.
        cache_key: The cache key (hash of script+temp+model).
    """
    if not svg or not cache_key:
        return

    def _save():
        try:
            from services.cache import cache_service, CacheFormat
            clean_svg = _extract_single_svg_document(svg)
            if not clean_svg.startswith("<svg") or "</svg>" not in clean_svg:
                return
            cache_service.set(cache_key, "svg", clean_svg, format=CacheFormat.SVG)
            _svg_save_logger.info(f"Saved SVG to cache (key: {cache_key[:8]}...)")
        except Exception as e:
            _svg_save_logger.warning(f"Could not save SVG to cache: {e}")

    threading.Thread(target=_save, daemon=True).start()
