"""
Run user pipeline code in an isolated namespace and output skrub's computation graph.

We extract the DAG as a dictionary using skrub's internal _Graph (not SVG):
  from skrub._data_ops._evaluation import _Graph
  graph = _Graph().run(dag)  # returns {"nodes", "parents", "children"}
  https://skrub-data.org/stable/reference/generated/skrub.DataOp.skb.draw_graph.html

The runner prints ##SKRUB_GRAPH##\\n{json}\\n##END## with a serializable graph dict so the
frontend can render an interactive DAG. If _Graph is unavailable, we fall back to
result.skb.draw_graph() SVG.

Flow: exec() the user code, take the result of the whole pipeline (last-assigned DataOp),
call _Graph().run(result), serialize to JSON, print ##SKRUB_GRAPH## block. Backend streams
that to the frontend for interactive visualization.

Also captures generated code from sempipes operators. Prints ##SEMPIPES_NODE_CODE##\\n{json}\\n##END##.
Emits execution stats (duration, LLM cost) via ##EXECUTION_STATS##.
"""
import json
import re
import sys
import time
import types
import importlib.machinery
import importlib.util
from contextlib import contextmanager

# Stub out heavy optional imports before sempipes tries to import them
# This allows sempipes to load even when these packages cause conflicts or are slow
def _create_stub_module(name):
    """Create a proper stub module with __spec__ so importlib checks don't fail."""
    spec = importlib.machinery.ModuleSpec(name, None)
    module = types.ModuleType(name)
    module.__spec__ = spec
    module.__file__ = f"<stub {name}>"
    module.__path__ = []
    module.__loader__ = None
    # Add commonly accessed attributes to prevent AttributeErrors
    module.__dict__.update({
        '__builtins__': {},
        '__cached__': None,
        '__package__': name.split('.')[0],
    })
    return module

# Stub imports that are either missing, conflicting, or too slow (tensorflow)
_STUB_IMPORTS = [
    "tensorflow",      # Too slow to import (hangs for 30+ seconds)
    "open_clip",       # Conflicts with autogluon timm requirement (not in safe_exec anyway)
]

for module_name in _STUB_IMPORTS:
    if module_name not in sys.modules:
        sys.modules[module_name] = _create_stub_module(module_name)

# Global list to capture LLM-generated code during exec.
_captured_codes = []
_original_generate_code = None
_unwrap_python_func = None

# Per-operator cost: litellm patch appends to _current_operator_costs when set; capture wrapper sums and appends to _per_operator_costs.
_current_operator_costs: list[float] | None = None
_per_operator_costs: list[float] = []
# Per-operator LLM attempt count (number of completion calls per operator).
_per_operator_attempts: list[int] = []


def _capturing_generate_code_from_messages(messages):
    """Wrapper that captures generated code and delegates to original function. Also attributes LLM cost and attempt count to this operator."""
    global _current_operator_costs
    _current_operator_costs = []
    try:
        raw_result = _original_generate_code(messages)
        _per_operator_attempts.append(len(_current_operator_costs))
        _per_operator_costs.append(sum(_current_operator_costs))
        # Unwrap to get clean Python code (remove markdown fences, etc.)
        clean_result = _unwrap_python_func(raw_result) if _unwrap_python_func else raw_result
        _captured_codes.append(clean_result)
        return raw_result  # Return raw result so generate_python_code_from_messages can unwrap it again
    finally:
        _current_operator_costs = None


def _setup_capture_patch():
    """
    Patch sempipes.llm.llm._generate_code_from_messages so we capture code regardless of import order.
    Operators import generate_python_code_from_messages which calls _generate_code_from_messages internally,
    so patching _generate_code_from_messages works even if operators have already imported the public function.
    """
    global _original_generate_code, _unwrap_python_func
    try:
        import sempipes.llm.llm
        from sempipes.llm.utils import unwrap_python

        # Save unwrap function so we can get clean Python code
        _unwrap_python_func = unwrap_python
        # Patch the internal function that all code generation goes through.
        _original_generate_code = sempipes.llm.llm._generate_code_from_messages
        sempipes.llm.llm._generate_code_from_messages = _capturing_generate_code_from_messages
        return True
    except ImportError:
        return False


def _prepare_globals():
    """Build globals for exec(): skrub, sempipes, os, common imports."""
    import os
    import sys

    g = {"__builtins__": __builtins__, "os": os}
    try:
        import skrub
        g["skrub"] = skrub
    except ImportError as e:
        print(f"Warning: Could not import skrub: {e}", file=sys.stderr)
    try:
        import sempipes
        g["sempipes"] = sempipes
        
        # Initialize sempipes config from environment variables (set by parent process)
        llm_name = os.environ.get("SEMPIPES_LLM_NAME")
        llm_temp = os.environ.get("SEMPIPES_LLM_TEMP")
        if llm_name and llm_temp:
            try:
                temp_value = float(llm_temp)
                sempipes.update_config(
                    llm_for_code_generation=sempipes.LLM(
                        name=llm_name,
                        parameters={"temperature": temp_value}
                    )
                )
                print(f"SEMPIPES> Configured LLM: {llm_name} (temp={temp_value})", file=sys.stderr)
            except (ValueError, Exception) as e:
                print(f"Warning: Failed to configure sempipes from env: {e}", file=sys.stderr)
    except ImportError as e:
        print(f"Warning: Could not import sempipes: {e}", file=sys.stderr)
    try:
        from sempipes import sem_choose
        g["sem_choose"] = sem_choose
    except ImportError:
        pass
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        g["HistGradientBoostingClassifier"] = HistGradientBoostingClassifier
    except ImportError:
        pass
    try:
        from sklearn.linear_model import LinearRegression
        g["LinearRegression"] = LinearRegression
    except ImportError:
        pass
    return g


def _is_dataop(val):
    """True if val has .skb.draw_graph() (skrub DataOp)."""
    try:
        skb = getattr(val, "skb", None)
        if skb is None:
            return False
        draw = getattr(skb, "draw_graph", None)
        return callable(draw)
    except Exception:
        return False


def _assignments_in_order(code):
    """
    Yield variable names from assignment statements in source order.
    Matches lines like '  result = ...' or 'x = ...'. Skips comments-only.
    """
    # Match line that has an assignment to a single identifier (no unpacking)
    pat = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=")
    for line in code.splitlines():
        # Ignore lines that are only comments
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        m = pat.match(line)
        if m:
            yield m.group(1)


_SKRUB_GRAPH_MARKER = "##SKRUB_GRAPH##"
_SKRUB_GRAPH_END = "##END##"
_SKRUB_GRAPH_SVG_MARKER = "##SKRUB_GRAPH_SVG##"
_NODE_PREVIEW_MARKER = "##NODE_PREVIEW##"
_EXECUTION_STATS_MARKER = "##EXECUTION_STATS##"
_NODE_INPUT_SUMMARY_MARKER = "##NODE_INPUT_SUMMARY##"

# Global list to accumulate LLM costs during execution
_execution_costs: list[float] = []


@contextmanager
def _track_litellm_costs():
    """
    Track costs from completion/batch_completion calls during pipeline execution.
    Patches sempipes.llm.llm (where sempipes actually calls the LLM) so cost is captured.
    Falls back to patching litellm when sempipes.llm.llm is not available.
    """
    global _execution_costs
    _execution_costs = []

    try:
        from litellm import completion_cost
    except ImportError:
        yield _execution_costs
        return

    try:
        import sempipes.llm.llm as llm_module
    except ImportError:
        llm_module = None

    def tracked_completion(original_completion, *args, **kwargs):
        response = original_completion(*args, **kwargs)
        try:
            c = completion_cost(completion_response=response)
            if c is not None:
                fc = float(c)
                _execution_costs.append(fc)
                if _current_operator_costs is not None:
                    _current_operator_costs.append(fc)
        except Exception:
            pass
        return response

    def tracked_batch_completion(original_batch, *args, **kwargs):
        responses = original_batch(*args, **kwargs)
        try:
            for resp in responses:
                c = completion_cost(completion_response=resp)
                if c is not None:
                    fc = float(c)
                    _execution_costs.append(fc)
                    if _current_operator_costs is not None:
                        _current_operator_costs.append(fc)
        except Exception:
            pass
        return responses

    if llm_module is not None:
        # Patch call site: sempipes.llm.llm uses completion/batch_completion (imported at load time).
        orig_completion = llm_module.completion
        orig_batch = getattr(llm_module, "batch_completion", None)
        llm_module.completion = lambda *a, **kw: tracked_completion(orig_completion, *a, **kw)
        if orig_batch is not None:
            llm_module.batch_completion = lambda *a, **kw: tracked_batch_completion(orig_batch, *a, **kw)
        try:
            yield _execution_costs
        finally:
            llm_module.completion = orig_completion
            if orig_batch is not None:
                llm_module.batch_completion = orig_batch
    else:
        # Fallback: patch litellm when sempipes not installed.
        import litellm
        original_completion = litellm.completion
        original_batch = getattr(litellm, "batch_completion", None)
        litellm.completion = lambda *a, **kw: tracked_completion(original_completion, *a, **kw)
        if original_batch is not None:
            litellm.batch_completion = lambda *a, **kw: tracked_batch_completion(original_batch, *a, **kw)
        try:
            yield _execution_costs
        finally:
            litellm.completion = original_completion
            if original_batch is not None:
                litellm.batch_completion = original_batch


def _get_pipeline_result_dataop(code, globals_dict):
    """Return the pipeline result DataOp (last-assigned DataOp in source order), or None."""
    dataop_names = set()
    for name, val in globals_dict.items():
        if name.startswith("_"):
            continue
        if _is_dataop(val):
            dataop_names.add(name)
    if not dataop_names:
        return None
    assignments = list(_assignments_in_order(code))
    for var_name in reversed(assignments):
        if var_name in dataop_names:
            return globals_dict[var_name]
    return None


def _is_sempipes_semantic_label(label):
    """True if this skrub node label corresponds to a sempipes semantic operator (LLM-generated code)."""
    if not label or not isinstance(label, str):
        return False
    low = label.strip().lower()
    if low.startswith("sem_"):
        return True
    if low in ("apply_with_sem_choose", "sem_choose"):
        return True
    # Specific sempipes estimator class names (from "Apply <Estimator>" runtime labels).
    # Only the classes that ARE sempipes semantic operators; standard ML estimators like
    # HistGradientBoostingClassifier are NOT semantic (they come from plain skb.apply()).
    _SEMANTIC_ESTIMATORS = (
        "llmimputer", "learnedimputer", "imputedlearner",
        "semfillnawithllm", "semfillnalllmplusmodel",
        "llmfeaturegenerator", "codebasedfeatureextractor", "caafe",
        "codedataaugmentor", "directdataaugmentor", "codeaugmentor",
        "llmcleaner", "semcleanwithllm",
        "llmdeduplicator", "semrefinewithllm",
        "llmcodegensemaggfeaturesestimator", "llmcodegensemaaggjoinfeaturesoperator", "semaggfeatures",
        "codedatadistiller", "semdistilldata",
        "llmfeatureextractor", "semextractfeaturesllm",
    )
    if any(e in low for e in _SEMANTIC_ESTIMATORS):
        return True
    return False


# Map skrub "Apply <X>" labels to sempipes operator display names.
# Graph shows sempipes operators (sem_fillna, sem_gen_features, etc.) so user can click to see generated code.
_APPLY_TO_SEMPIPES = {
    "llmimputer": "sem_fillna",
    "imputedlearner": "sem_fillna",
    "semfillnawithllm": "sem_fillna",
    "semfillnalllmplusmodel": "sem_fillna",
    "codebasedfeatureextractor": "sem_gen_features",
    "caafe": "sem_gen_features",
    "codedataaugmentor": "sem_augment",
    "codeaugmentor": "sem_augment",
    "selectcols": "sem_select",
}


def _apply_label_to_sempipes_operator(label):
    """
    Replace skrub Apply node label with sempipes operator name for display.
    E.g. "Apply ImputedLearner" -> "sem_fillna". Unknown Apply X is left as-is.
    """
    if not label or not isinstance(label, str):
        return label
    stripped = label.strip()
    low = stripped.lower()
    if not low.startswith("apply "):
        return stripped
    # "Apply ImputedLearner" -> key "imputedlearner"
    suffix = low[6:].strip()  # after "apply "
    if not suffix:
        return stripped
    # Normalize: remove spaces (e.g. "Apply ImputedLearner" -> "imputedlearner")
    key = "".join(suffix.split()).lower()[:80]
    if key in _APPLY_TO_SEMPIPES:
        return _APPLY_TO_SEMPIPES[key]
    for apply_key, sem_name in _APPLY_TO_SEMPIPES.items():
        if apply_key in key or key in apply_key:
            return sem_name
    return stripped


def _topological_order(node_ids, parents_map):
    """Return node_ids in topological order (roots first, then nodes whose parents are done)."""
    done = set()
    result = []
    pending = list(node_ids)
    while pending:
        made_progress = False
        next_round = []
        for nid in pending:
            preds = parents_map.get(nid, [])
            if all(p in done for p in preds):
                done.add(nid)
                result.append(nid)
                made_progress = True
            else:
                next_round.append(nid)
        if not made_progress:
            # cycles or missing refs: add rest in order
            result.extend(next_round)
            break
        pending = next_round
    return result


def _graph_to_serializable(raw):
    """
    Convert _Graph().run(dag) output to JSON-serializable dict.
    raw has "nodes", "parents", "children". Nodes may be objects; we use index as id.
    Replaces skrub Apply primitives (e.g. "Apply ImputedLearner") with sempipes operator names
    (e.g. "sem_fillna") so the graph shows sempipes operators; user can click them to see generated code.
    Tags sempipes semantic operators and emits sempipesNodeIds in execution (topo) order.
    """
    nodes_raw = raw.get("nodes") or []
    parents_raw = raw.get("parents") or {}
    children_raw = raw.get("children") or {}

    node_list = list(nodes_raw) if not isinstance(nodes_raw, dict) else list(nodes_raw.values())
    obj_to_idx = {}
    for i, n in enumerate(node_list):
        try:
            obj_to_idx[id(n)] = i
        except TypeError:
            obj_to_idx[i] = i

    def label_for(node, i):
        if node is None:
            return f"node_{i}"
        # Prefer skrub's short representation (matches DataOp.__skrub_short_repr__)
        try:
            short_repr = getattr(node, "__skrub_short_repr__", None)
            if callable(short_repr):
                lab = short_repr()
                if lab is not None and isinstance(lab, str) and lab.strip():
                    return lab[:80]
        except Exception:
            pass
        for attr in ("description", "name", "label"):
            try:
                v = getattr(node, attr, None)
                if v is not None and isinstance(v, str):
                    return v[:80]
            except Exception:
                pass
        try:
            return str(node)[:80]
        except Exception:
            return f"node_{i}"

    nodes = []
    for i, n in enumerate(node_list):
        lab = label_for(n, i)
        is_sem = _is_sempipes_semantic_label(lab)
        display_label = _apply_label_to_sempipes_operator(lab) if is_sem else lab
        nodes.append({
            "id": str(i),
            "label": display_label,
            "is_sempipes_semantic": is_sem,
        })

    def to_id_list(lst, n):
        if not isinstance(lst, (list, tuple)):
            return []
        result = []
        for x in lst:
            if isinstance(x, int) and 0 <= x < n:
                result.append(str(x))
            else:
                result.append(str(obj_to_idx.get(id(x), x)))
        return result

    def _safe_graph_lookup(d, int_idx, node_ref):
        """Look up a value in a graph dict that may use int or unhashable (DataOp) keys."""
        try:
            val = d.get(int_idx)
            if val:
                return val
        except Exception:
            pass
        # Scan by object identity (handles DataOp-keyed dicts where DataOp is unhashable)
        ref_id = id(node_ref)
        for key, val in d.items():
            if id(key) == ref_id:
                return val or []
        return []

    n = len(node_list)
    parents = {}
    children = {}
    for i in range(n):
        si = str(i)
        node_ref = node_list[i] if i < len(node_list) else i
        p = _safe_graph_lookup(parents_raw, i, node_ref)
        c = _safe_graph_lookup(children_raw, i, node_ref)
        parents[si] = to_id_list(p, n)
        children[si] = to_id_list(c, n)

    # Sempipes semantic nodes in topological (execution) order → index matches _captured_codes order
    all_ids = [no["id"] for no in nodes]
    topo = _topological_order(all_ids, parents)
    sempipes_node_ids = [nid for nid in topo if next((no for no in nodes if no["id"] == nid), {}).get("is_sempipes_semantic")]

    return {
        "nodes": nodes,
        "parents": parents,
        "children": children,
        "sempipesNodeIds": sempipes_node_ids,
    }


def _extract_preview_from_dataop(node_obj, node_id):
    """
    Extract preview data (schema, sample, row_count) from a DataOp using .skb.preview().
    Returns dict with node_id, schema, sample, row_count; or None if preview fails.
    """
    try:
        # Check if this object has .skb.preview()
        skb = getattr(node_obj, "skb", None)
        if skb is None:
            return None
        preview_func = getattr(skb, "preview", None)
        if not callable(preview_func):
            return None

        # Get preview data
        preview_data = preview_func()
        if preview_data is None:
            return None

        # Import pandas to check DataFrame type
        try:
            import pandas as pd
            is_dataframe = isinstance(preview_data, pd.DataFrame)
        except ImportError:
            is_dataframe = hasattr(preview_data, "columns") and hasattr(preview_data, "dtypes")

        if is_dataframe:
            # Extract schema (column names and dtypes)
            schema = [
                {"name": str(col), "dtype": str(preview_data[col].dtype)}
                for col in preview_data.columns
            ]
            # Extract sample rows (first 5 rows as dicts)
            sample = preview_data.head(5).to_dict(orient="records")
            # Clean up sample values for JSON serialization
            for row in sample:
                for key, val in list(row.items()):
                    if hasattr(val, "item"):  # numpy scalar
                        row[key] = val.item()
                    elif val is None or (isinstance(val, float) and (val != val)):  # NaN
                        row[key] = None
            row_count = len(preview_data)
            return {
                "node_id": node_id,
                "schema": schema,
                "sample": sample,
                "row_count": row_count,
            }
        else:
            # Non-DataFrame preview (e.g. Series, scalar)
            # Try to convert to a simple representation
            return {
                "node_id": node_id,
                "schema": [{"name": "value", "dtype": str(type(preview_data).__name__)}],
                "sample": [{"value": str(preview_data)[:200]}],
                "row_count": 1,
            }
    except Exception as e:
        # Preview failed - this is expected for some node types
        print(f"Warning: Could not get preview for node {node_id}: {e}", file=sys.stderr)
        return None


def _extract_all_previews(raw_graph):
    """
    Extract preview data for all nodes in the graph using .skb.preview().
    Returns list of preview dicts (node_id, schema, sample, row_count).
    """
    if not raw_graph or not isinstance(raw_graph, dict):
        return []

    nodes_raw = raw_graph.get("nodes") or []
    node_list = list(nodes_raw) if not isinstance(nodes_raw, dict) else list(nodes_raw.values())

    previews = []
    for i, node_obj in enumerate(node_list):
        node_id = str(i)
        preview = _extract_preview_from_dataop(node_obj, node_id)
        if preview:
            previews.append(preview)

    return previews


def _get_skrub_dag_dict(code, globals_dict):
    """
    Get skrub DAG as a serializable dict using _Graph().run(result) and native SVG from draw_graph().
    Returns (graph_dict, svg_str, previews). graph_dict for interactive DAG; svg_str for native skrub SVG;
    previews is list of node preview data (schema, sample, row_count).
    """
    result = _get_pipeline_result_dataop(code, globals_dict)
    if result is None:
        return None, None, []

    graph_dict = None
    svg_str = None
    previews = []
    raw_graph = None

    # Try _Graph().run() for interactive DAG; separate try/except so preview extraction
    # still runs even if graph serialization fails (e.g. unhashable DataOp keys).
    try:
        from skrub._data_ops._evaluation import _Graph
        raw_graph = _Graph().run(result)
    except Exception:
        raw_graph = None

    if raw_graph and isinstance(raw_graph, dict) and "nodes" in raw_graph:
        try:
            graph_dict = _graph_to_serializable(raw_graph)
        except Exception:
            pass
        try:
            previews = _extract_all_previews(raw_graph)
        except Exception:
            pass

    # Always try draw_graph() for native skrub SVG (for saving to disk)
    try:
        graph = result.skb.draw_graph()
        if graph:
            svg = getattr(graph, "svg", None)
            if svg:
                svg_str = svg.decode("utf-8") if isinstance(svg, bytes) else str(svg)
    except Exception:
        pass

    return graph_dict, svg_str, previews


def _df_to_summary(df, var_name: str) -> dict | None:
    """Convert a pandas DataFrame to a JSON-serialisable summary dict."""
    try:
        schema = [{"name": str(col), "dtype": str(df[col].dtype)} for col in df.columns]
        sample = df.head(5).to_dict(orient="records")
        for row in sample:
            for key, val in list(row.items()):
                if hasattr(val, "item"):  # numpy scalar
                    row[key] = val.item()
                elif val is None or (isinstance(val, float) and (val != val)):  # NaN
                    row[key] = None
                elif not isinstance(val, (str, int, float, bool, type(None))):
                    row[key] = str(val)
        return {"var_name": var_name, "schema": schema, "sample": sample, "row_count": len(df)}
    except Exception as e:
        print(f"Warning: Could not summarise {var_name}: {e}", file=sys.stderr)
        return None


def _extract_var_input_summaries(g: dict) -> list[dict]:
    """
    Extract real data summaries for pipeline input variables after exec().

    Looks in two places (in priority order):
    1. g["env"] — set by pipeline.skb.get_data(); contains the actual DataFrames fed to
       the pipeline (e.g. env["products"] = dataset.products).
    2. g directly — plain DataFrame variables assigned at script top-level.

    Returns list of dicts: {var_name, schema, sample, row_count}.
    Never returns placeholder data — skips variables that cannot be summarised.
    """
    try:
        import pandas as pd
    except ImportError:
        return []

    summaries: list[dict] = []
    seen: set[str] = set()

    # Priority 1: g["env"] (pipeline data environment)
    env = g.get("env")
    if isinstance(env, dict):
        for var_name, val in env.items():
            if isinstance(var_name, str) and not var_name.startswith("_"):
                if isinstance(val, pd.DataFrame):
                    s = _df_to_summary(val, var_name)
                    if s:
                        summaries.append(s)
                        seen.add(var_name)

    # Priority 2: top-level DataFrame variables in g
    for var_name, val in g.items():
        if var_name in seen or var_name.startswith("_") or not isinstance(var_name, str):
            continue
        if isinstance(val, pd.DataFrame):
            s = _df_to_summary(val, var_name)
            if s:
                summaries.append(s)
                seen.add(var_name)

    return summaries


def main():
    code = sys.stdin.read()

    # Set up capture patch BEFORE preparing globals (which may trigger operator imports).
    # This replaces sempipes.llm.llm.generate_python_code_from_messages before operators see it.
    _setup_capture_patch()

    g = _prepare_globals()
    exec_failed = False

    # Clear per-operator costs and attempts from any previous run (e.g. if module is reused)
    _per_operator_costs.clear()
    _per_operator_attempts.clear()

    # Track execution time and LLM costs
    exec_start = time.perf_counter()
    with _track_litellm_costs() as costs:
        try:
            exec(code, g)
        except Exception:
            exec_failed = True
    exec_duration_ms = (time.perf_counter() - exec_start) * 1000
    total_cost_usd = sum(_per_operator_costs)

    # Emit real data summaries for input variables (from g["env"] or top-level DataFrames).
    # Only emitted when actual data is available — never placeholder/fake data.
    input_summaries = _extract_var_input_summaries(g)
    for s in input_summaries:
        print(_NODE_INPUT_SUMMARY_MARKER)
        print(json.dumps(s))
        print(_SKRUB_GRAPH_END)

    # Extract skrub DAG first so we can emit skrub_node_id with each code block (fixes code-to-node mapping).
    graph_dict, svg_str, previews = _get_skrub_dag_dict(code, g)
    sempipes_node_ids = list(graph_dict.get("sempipesNodeIds", [])) if graph_dict else []

    # Emit captured operator-generated code so backend can emit node_code (no bypass). Include skrub_node_id
    # so backend can map code to the correct node regardless of execution vs document order.
    for i, code_str in enumerate(_captured_codes):
        cost_usd = _per_operator_costs[i] if i < len(_per_operator_costs) else 0.0
        attempts = _per_operator_attempts[i] if i < len(_per_operator_attempts) else 1
        payload = {"index": i, "code": code_str, "cost_usd": cost_usd, "attempts": attempts}
        if i < len(sempipes_node_ids):
            payload["skrub_node_id"] = sempipes_node_ids[i]
        print("##SEMPIPES_NODE_CODE##")
        print(json.dumps(payload))
        print("##END##")
    if graph_dict:
        print(_SKRUB_GRAPH_MARKER)
        print(json.dumps(graph_dict))
        print(_SKRUB_GRAPH_END)
    if svg_str:
        # Emit native skrub SVG for saving to disk (backend replaces by script name)
        print(_SKRUB_GRAPH_SVG_MARKER)
        print(svg_str, end="")
        print("\n" + _SKRUB_GRAPH_END)
    # Emit node previews (intermediate data for each node)
    for preview in previews:
        print(_NODE_PREVIEW_MARKER)
        print(json.dumps(preview))
        print(_SKRUB_GRAPH_END)

    # Emit execution stats (duration and cost)
    print(_EXECUTION_STATS_MARKER)
    print(json.dumps({"duration_ms": exec_duration_ms, "cost_usd": total_cost_usd}))
    print(_SKRUB_GRAPH_END)

    if exec_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
