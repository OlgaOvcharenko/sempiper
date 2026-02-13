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


def _normalize_skrub_label(label: str) -> str:
    """
    Normalize skrub internal labels to frontend-friendly display labels.

    Transforms:
        <Var 'products'> -> products (var name)
        <SubsamplePreviews> -> skb.subsample
        <Apply LearnedImputer> -> sem_fillna
        <Apply LLMFeatureGenerator> -> sem_gen_features
        <GetItem 'col'> -> getitem
        etc.
    """
    if not label or not isinstance(label, str):
        return label or "unknown"

    label = label.strip()

    # Handle <Var 'name'> pattern
    import re
    var_match = re.match(r"<Var\s*['\"]([^'\"]+)['\"]>", label)
    if var_match:
        name = var_match.group(1)
        # Check for sempipes internal vars
        if name.startswith("sempipes_"):
            return name  # Keep as-is for internal sempipes vars
        return name  # Return the variable name

    # Handle <SubsamplePreviews> or <Subsample>
    if "subsample" in label.lower():
        return "skb.subsample"

    # Handle <Apply X> patterns -> map to sempipes operators
    apply_match = re.match(r"<Apply\s+(\w+)>", label)
    if apply_match:
        estimator = apply_match.group(1).lower()
        # Map known estimators to sempipes operators
        if estimator in ("learnedimputer", "llmimputer", "imputedlearner"):
            return "sem_fillna"
        if estimator in ("llmfeaturegenerator", "codebasedfeatureextractor", "caafe"):
            return "sem_gen_features"
        if estimator in ("codedataaugmentor", "codeaugmentor"):
            return "sem_augment"
        if estimator in ("selectcols",):
            return "sem_select"
        if estimator in ("tablevectorizer",):
            return "TableVectorizer"
        if estimator in ("histgradientboostingclassifier",):
            return "apply_with_sem_choose"
        return f"Apply {apply_match.group(1)}"

    # Handle <EvalMode>
    if label == "<EvalMode>":
        return "skb.eval"

    # Handle <GetItem 'col'> or <GetItem ['cols']>
    if label.startswith("<GetItem"):
        return "getitem"

    # Handle <CallMethod 'name'>
    method_match = re.match(r"<CallMethod\s*['\"]([^'\"]+)['\"]>", label)
    if method_match:
        return method_match.group(1)

    # Handle <Call 'name'>
    call_match = re.match(r"<Call\s*['\"]([^'\"]+)['\"]>", label)
    if call_match:
        return call_match.group(1)

    # Remove angle brackets for other patterns
    if label.startswith("<") and label.endswith(">"):
        return label[1:-1]

    return label


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


def rewrite_script_for_graph_extraction(script: str) -> str:
    """
    Rewrite a pipeline script for graph extraction without data execution.

    Transformations:
    1. Remove data arguments from skrub.var() calls
    2. Remove .skb.eval() calls

    Args:
        script: Original pipeline script

    Returns:
        Rewritten script that can be executed to build the computation graph
        without requiring actual data or triggering computation.
    """
    script = _rewrite_var_calls(script)
    script = _remove_eval_calls(script)
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


def extract_skrub_graph(script: str) -> SkrubGraphResult:
    """
    Extract the real skrub computation graph by executing a rewritten script.

    This function:
    1. Rewrites the script to remove data arguments and eval calls
    2. Executes the rewritten script to build the computation graph
    3. Extracts the graph structure using skrub's internal graph() function

    Args:
        script: Python source code containing pipeline declarations

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
    # Rewrite the script
    rewritten = rewrite_script_for_graph_extraction(script)

    # Prepare execution globals
    exec_globals = {"__builtins__": __builtins__}

    try:
        import skrub
        exec_globals["skrub"] = skrub
    except ImportError as e:
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

    # Add common sklearn imports
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

    # Execute the rewritten script
    try:
        exec(rewritten, exec_globals)
    except Exception as e:
        return SkrubGraphResult(
            nodes=[],
            parents={},
            children={},
            rewritten_script=rewritten,
            error=f"Execution failed: {e}",
        )

    # Find the last DataOp
    data_op = _get_last_dataop(exec_globals, rewritten)
    if data_op is None:
        return SkrubGraphResult(
            nodes=[],
            parents={},
            children={},
            rewritten_script=rewritten,
            error="No DataOp found in executed script",
        )

    # Extract the graph using skrub's internal function
    try:
        from skrub._data_ops._evaluation import graph as skrub_graph
        raw = skrub_graph(data_op)
        return _graph_to_result(raw, rewritten)
    except ImportError:
        # Fallback to _Graph class
        try:
            from skrub._data_ops._evaluation import _Graph
            raw = _Graph().run(data_op)
            return _graph_to_result(raw, rewritten)
        except Exception as e:
            return SkrubGraphResult(
                nodes=[],
                parents={},
                children={},
                rewritten_script=rewritten,
                error=f"Graph extraction failed: {e}",
            )
    except Exception as e:
        return SkrubGraphResult(
            nodes=[],
            parents={},
            children={},
            rewritten_script=rewritten,
            error=f"Graph extraction failed: {e}",
        )


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

    # Handle <Apply X> patterns
    apply_match = re.match(r"<apply\s+(\w+)>", low)
    if apply_match:
        estimator = apply_match.group(1).lower()
        if estimator in ("learnedimputer", "llmimputer", "imputedlearner"):
            return "sem_fillna"
        if estimator in ("llmfeaturegenerator", "codebasedfeatureextractor", "caafe"):
            return "sem_gen_features"
        if estimator in ("codedataaugmentor", "codeaugmentor"):
            return "sem_augment"
        if estimator in ("histgradientboostingclassifier",):
            return "apply_with_sem_choose"
        if estimator in ("tablevectorizer",):
            return "tablevectorizer"
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


def compile_script_to_graph_dynamic(script: str) -> GraphResult:
    """
    Compile a pipeline script using dynamic extraction (real skrub graph).

    This executes a rewritten version of the script (with data args removed
    and eval calls replaced) to get the actual computation graph from skrub.

    Falls back to static parsing if dynamic extraction fails.

    Args:
        script: Python source code containing pipeline declarations.

    Returns:
        GraphResult with nodes, edges, and validation_errors.
    """
    # Try dynamic extraction first
    skrub_result = extract_skrub_graph(script)

    if skrub_result.is_valid:
        # Get base result from skrub
        result = skrub_result.to_graph_result()

        # Fuse sempipes internal nodes into single semantic operator nodes
        from services.graph_fusion import fuse_graph
        result.nodes, result.edges = fuse_graph(result.nodes, result.edges)

        # Merge source ranges from static parsing for code-graph sync
        static_result = compile_script_to_graph(script)
        if static_result.nodes:
            result.nodes = _merge_source_ranges(result.nodes, static_result.nodes)

        return result

    # Fall back to static parsing
    return compile_script_to_graph(script)
