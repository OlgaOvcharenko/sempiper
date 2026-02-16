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

import re
import time
from dataclasses import dataclass, field

from models.schemas import CompileEdge, CompileNode
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


def rewrite_script_for_graph_extraction(script: str) -> str:
    """
    Rewrite a pipeline script for graph extraction without full execution.

    Preprocessing:
    - Remove skrub.datasets.fetch_*() so we don't run dataset load during exec.
    - Strip the data argument from skrub.var(name, data) -> skrub.var(name), e.g.:
      products = skrub.var("products", dataset.products)  ->  products = skrub.var("products")

    Transformations:
    1. skrub.datasets.fetch_*(...) -> assign None (preprocessing: no dataset load).
    2. skrub.var("name", data) -> skrub.var("name") (preprocessing: no data argument).
    3. Remove .skb.eval() calls (so we don't materialize the pipeline).
    4. Remove .skb.cross_validate() calls (so we don't run CV; keep the DataOp for graph).

    Args:
        script: Original pipeline script

    Returns:
        Rewritten script that can be executed to build the computation graph.
    """
    script = _remove_skrub_datasets_fetches(script)
    script = _rewrite_var_calls(script)
    script = _remove_eval_calls(script)
    script = _remove_cross_validate_calls(script)
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
            return _graph_to_result(raw, rewritten)
        except ImportError:
            try:
                from skrub._data_ops._evaluation import _Graph
                raw = _Graph().run(data_op)
                if timings_out is not None:
                    timings_out["skrub_graph_ms"] = (time.perf_counter() - t0) * 1000
                return _graph_to_result(raw, rewritten)
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


def _merge_source_ranges(
    skrub_nodes: list[CompileNode],
    static_nodes: list[CompileNode],
) -> list[CompileNode]:
    """
    Merge source_range information from static parsing into skrub nodes.

    Matches nodes by extracting keys from raw skrub labels and matching
    against static node labels for code-graph synchronization.

    BUG FIX: Uses a list to track all occurrences of each label, so that
    pipelines with multiple calls to the same operator (e.g., two sem_gen_features)
    can each get their correct source_range.
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

        if key in label_to_ranges:
            # Get the Nth occurrence of this label's source_range
            occurrence = label_usage.get(key, 0)
            ranges = label_to_ranges[key]
            if occurrence < len(ranges):
                source_range = ranges[occurrence]
                label_usage[key] = occurrence + 1

        result.append(CompileNode(
            id=node.id,
            type=node.type,
            label=node.label,
            source_range=source_range,
        ))
    return result


def compile_script_to_graph_dynamic(
    script: str,
    timings_out: dict[str, float] | None = None,
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

    Returns:
        GraphResult with nodes, edges, and validation_errors.
    """
    # Single static parse for source ranges (reused in merge step; avoids duplicate compile_script_to_graph)
    t0 = time.perf_counter()
    static_nodes, _ = extract_nodes_with_ranges(script)
    if timings_out is not None:
        timings_out["static_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    skrub_result = extract_skrub_graph(script, timings_out=timings_out)
    if timings_out is not None:
        timings_out["extract_ms"] = (time.perf_counter() - t0) * 1000

    if not skrub_result.is_valid:
        return GraphResult(
            nodes=[],
            edges=[],
            validation_errors=[skrub_result.error] if skrub_result.error else [],
        )

    # Get base result from skrub
    result = skrub_result.to_graph_result()

    t0 = time.perf_counter()
    from services.graph_fusion import fuse_graph
    result.nodes, result.edges = fuse_graph(result.nodes, result.edges)
    if timings_out is not None:
        timings_out["fuse_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    if static_nodes:
        result.nodes = _merge_source_ranges(result.nodes, static_nodes)
    if timings_out is not None:
        timings_out["merge_ms"] = (time.perf_counter() - t0) * 1000

    return result
