"""
Run user pipeline code in an isolated namespace and output skrub's computational graph.

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
import traceback
import types
import importlib.machinery
import importlib.util
import io
from contextlib import contextmanager, redirect_stdout

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

# Stub imports that are either missing or conflicting (not in safe_exec anyway)
_STUB_IMPORTS = [
    "open_clip",       # Conflicts with autogluon timm requirement
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

# Per-code object-identity tracking: records id(data_op) at the time each LLM call happens,
# so main() can resolve the correct skrub node index without relying on execution order.
_captured_code_node_ids: list[int | None] = []
_current_node_object_id: int | None = None
# Ref-based tracking: stores the actual DataOp reference (not just id()) so GC cannot
# reuse the memory address and cause a false identity match in the post-exec graph walk.
_captured_code_node_refs: list = []
_current_node_object_ref = None

# Node preview capture: populated by _setup_preview_capture_patch during exec.
# Maps id(data_op) -> {schema, sample, row_count} captured during evaluate callback.
_captured_previews: dict = {}
_preview_capture_installed: bool = False  # Guard against double-patching.


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
        # Record which DataOp object is currently being evaluated so main() can
        # resolve the correct skrub node index for this code block via obj_to_idx.
        _captured_code_node_ids.append(_current_node_object_id)
        # Also store the actual reference — prevents GC from reusing the address before
        # the post-exec _G().run() walk, allowing reliable `is` identity comparison.
        _captured_code_node_refs.append(_current_node_object_ref)
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


def _setup_preview_capture_patch():
    """Patch skrub's evaluate() to capture node previews during the first pipeline run.

    When learner.fit(env) runs inside exec(), it calls evaluate(mode='fit_transform',
    clear=True). The clear=True path invokes callbacks after each node; we inject one
    that converts the result to a summary dict before it is pruned from memory.

    After exec(), _captured_previews maps id(data_op) -> {schema, sample, row_count}
    for every evaluated node, so _get_skrub_dag_dict can skip the second evaluate pass.
    """
    global _preview_capture_installed
    if _preview_capture_installed:
        return
    try:
        import skrub._data_ops._evaluation as _eval_mod
    except ImportError:
        return

    original_evaluate = _eval_mod.evaluate

    def _capturing_evaluate(data_op, mode="preview", environment=None, clear=False, callbacks=()):
        global _current_node_object_id, _current_node_object_ref
        prev_node_obj_id  = _current_node_object_id
        prev_node_obj_ref = _current_node_object_ref
        _current_node_object_id  = id(data_op)
        _current_node_object_ref = data_op  # keep alive so its id() cannot be reused
        try:
            if clear and mode in ("fit", "fit_transform"):
                def _capture(da, result):
                    try:
                        df = _to_dataframe(result)
                        if df is not None:
                            d = _dataframe_to_preview_dict(df, "")
                            if d:
                                d.pop("node_id", None)
                                _captured_previews[id(da)] = d
                    except Exception:
                        pass
                callbacks = (*callbacks, _capture)
            return original_evaluate(data_op, mode=mode, environment=environment,
                                     clear=clear, callbacks=callbacks)
        finally:
            _current_node_object_id  = prev_node_obj_id
            _current_node_object_ref = prev_node_obj_ref

    _eval_mod.evaluate = _capturing_evaluate
    # Also patch local bindings in modules that imported evaluate via
    # `from ._evaluation import evaluate` — patching _eval_mod alone won't
    # reach those local references.
    for _mod_name in (
        "skrub._data_ops._skrub_namespace",
        "skrub._data_ops._estimator",
    ):
        try:
            _mod = importlib.import_module(_mod_name)
            _mod.evaluate = _capturing_evaluate
        except Exception:
            pass
    _preview_capture_installed = True


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
_VAR_PREVIEW_MARKER = "##VAR_PREVIEW##"
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

    # apply_with_sem_choose is represented by a plain sklearn estimator apply node.
    # Example label: "<Apply HistGradientBoostingClassifier>"
    # (sem_choose hyperparameters are decided via the sem_choose LLM code path).
    _APPLY_WITH_SEM_CHOOSE_ESTIMATORS = (
        "histgradientboostingclassifier",
        "histgradientboostingregressor",
        "randomforestclassifier",
        "randomforestregressor",
        "gradientboostingclassifier",
        "gradientboostingregressor",
        "xgbclassifier",
        "xgbregressor",
        "lgbmclassifier",
        "lgbmregressor",
    )
    if any(e in low for e in _APPLY_WITH_SEM_CHOOSE_ESTIMATORS):
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

    # Map "<Apply HistGradientBoostingClassifier>" -> "apply_with_sem_choose".
    _APPLY_WITH_SEM_CHOOSE_ESTIMATORS = (
        "histgradientboostingclassifier",
        "histgradientboostingregressor",
        "randomforestclassifier",
        "randomforestregressor",
        "gradientboostingclassifier",
        "gradientboostingregressor",
        "xgbclassifier",
        "xgbregressor",
        "lgbmclassifier",
        "lgbmregressor",
    )
    if any(e in low for e in _APPLY_WITH_SEM_CHOOSE_ESTIMATORS):
        return "apply_with_sem_choose"

    # Handle skrub "<Apply X>" labels (lower() starts with "<apply ").
    # Normalize to "apply ..." before parsing the suffix.
    low_norm = low.lstrip("<").strip()
    if not low_norm.startswith("apply "):
        return stripped

    # "Apply ImputedLearner" -> key "imputedlearner"
    suffix = low_norm[6:].strip()  # after "apply "
    # Strip trailing decorators like ">" from "<Apply ...>"
    suffix = suffix.rstrip(">").strip()

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


def _map_captures_to_skrub_semantic_nodes(
    num_captures: int,
    ref_to_graph_idx: dict[int, int],
    semantic_node_ids: set[str],
) -> dict[int, str]:
    """
    Map each LLM code-capture index to a skrub graph node id (string) for semantic operators.
    Prefer object-identity ref match; if some captures lack a match, pair remaining captures
    to remaining semantic nodes in numeric node-id order (matches typical pipeline order).
    """
    ordered_semantic = sorted(semantic_node_ids, key=lambda x: int(x)) if semantic_node_ids else []
    capture_to_skrub: dict[int, str] = {}
    for i in range(num_captures):
        gi = ref_to_graph_idx.get(i)
        if gi is not None:
            sid = str(gi)
            if sid in semantic_node_ids:
                capture_to_skrub[i] = sid
    assigned_semantic = set(capture_to_skrub.values())
    remaining_semantic = [s for s in ordered_semantic if s not in assigned_semantic]
    unresolved = [i for i in range(num_captures) if i not in capture_to_skrub]
    # If ref matching can't resolve all captures, pair the remaining captures with the first
    # remaining semantic nodes in numeric order. This handles cases where runtime graphs expose
    # extra semantic slots (e.g. apply_with_sem_choose nodes) but the pipeline only emits fewer
    # LLM code captures.
    #
    # We intentionally do NOT require counts to match exactly: requiring equality turns this
    # into a hard failure mode (no code emission), which breaks node assignment for some
    # pipelines like `simple` and `medium`.
    if remaining_semantic:
        for cap_idx, sem_id in zip(sorted(unresolved), remaining_semantic):
            capture_to_skrub[cap_idx] = sem_id
    return capture_to_skrub


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


def _nodes_to_list(nodes_raw) -> list:
    """Normalize raw_graph["nodes"] to a list (handles both dict and list formats)."""
    return list(nodes_raw) if not isinstance(nodes_raw, dict) else list(nodes_raw.values())


_ENV_KEYS = ("env", "env_train", "env_test", "environment", "train_env", "data_env")


def _find_env_dict(g: dict) -> dict | None:
    """Return the first dict value in g matching a standard environment key name."""
    for key in _ENV_KEYS:
        cand = g.get(key)
        if isinstance(cand, dict):
            return cand
    return None


def _find_learner_dataop(globals_dict: dict):
    """Return the SkrubLearner's internal DataOp from globals, or None.

    make_learner() clones the pipeline DataOp before fitting, so the captured
    node IDs in _captured_previews come from clone nodes, not the original.
    Using the learner's data_op as the source for _Graph().run() gives us a
    raw_graph whose node objects match the captured IDs.

    Prefers a fully fitted learner, but falls back to any SkrubLearner found
    in globals. This handles the case where exec() failed mid-fit (so the
    learner is not fully fitted) but captures still came from the clone.
    """
    try:
        from skrub._data_ops._estimator import SkrubLearner
    except ImportError:
        return None
    fitted = None
    any_learner = None
    for val in globals_dict.values():
        if isinstance(val, SkrubLearner):
            if getattr(val, "_is_fitted", False):
                fitted = val.data_op
                break
            elif any_learner is None:
                any_learner = val.data_op
    return fitted if fitted is not None else any_learner


def _graph_to_serializable(raw):
    """
    Convert _Graph().run(dag) output to JSON-serializable dict.
    raw has "nodes", "parents", "children". Nodes may be objects; we use index as id.
    Replaces skrub Apply primitives (e.g. "Apply ImputedLearner") with sempipes operator names
    (e.g. "sem_fillna") so the graph shows sempipes operators; user can click them to see generated code.
    Tags sempipes semantic operators; sempipesNodeIds sorted by numeric node index (stable vs graph cycles).
    """
    nodes_raw = raw.get("nodes") or []
    parents_raw = raw.get("parents") or {}
    children_raw = raw.get("children") or {}

    node_list = _nodes_to_list(nodes_raw)
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

    # Semantic skrub node ids in stable pipeline order. Full-graph topo is unreliable (e.g. cycles
    # between Apply and Value dict nodes; sinks with empty parents). Numeric index order matches
    # typical left-to-right pipeline layout and pairs with LLM capture order when ref-matching fails.
    sempipes_node_ids = sorted(
        (no["id"] for no in nodes if no.get("is_sempipes_semantic")),
        key=lambda x: int(x),
    )

    return {
        "nodes": nodes,
        "parents": parents,
        "children": children,
        "sempipesNodeIds": sempipes_node_ids,
    }


def _dataframe_to_preview_dict(preview_data, node_id):
    """Build preview dict (node_id, schema, sample, row_count) from a pandas DataFrame."""
    try:
        import pandas as pd
        is_dataframe = isinstance(preview_data, pd.DataFrame)
    except ImportError:
        is_dataframe = hasattr(preview_data, "columns") and hasattr(preview_data, "dtypes")
    if not is_dataframe:
        return None
    schema = [
        {"name": str(col), "dtype": str(preview_data[col].dtype)}
        for col in preview_data.columns
    ]
    sample = preview_data.head(5).to_dict(orient="records")
    for row in sample:
        for key, val in list(row.items()):
            if hasattr(val, "item"):
                row[key] = val.item()
            elif val is None or (isinstance(val, float) and (val != val)):
                row[key] = None
    return {
        "node_id": node_id,
        "schema": schema,
        "sample": sample,
        "row_count": len(preview_data),
    }


def _evaluate_and_cache_all_nodes(result_dataop, env):
    """Evaluate the full graph once with clear=False so all node results are cached.

    After this call, every node in the graph has its result stored in
    node._skrub_impl.results["fit_transform"], enabling O(1) lookups
    in _extract_preview_from_dataop without re-executing the pipeline.
    """
    try:
        from skrub._data_ops._evaluation import evaluate
        evaluate(result_dataop, mode="fit_transform", environment=env, clear=False)
        return True
    except Exception as e:
        print(f"Warning: single-pass evaluate failed, previews may be incomplete: {e}", file=sys.stderr)
        return False


def _to_dataframe(val):
    """Convert Series or ndarray to DataFrame; return DataFrame as-is; return None otherwise."""
    try:
        import pandas as pd
    except ImportError:
        return None
    if isinstance(val, pd.DataFrame):
        return val
    if isinstance(val, pd.Series):
        return val.to_frame()
    try:
        import numpy as np
        if isinstance(val, np.ndarray) and val.ndim <= 2:
            return pd.DataFrame(val)
    except ImportError:
        pass
    return None


def _extract_preview_from_dataop(node_obj, node_id):
    """
    Extract preview data (schema, sample, row_count) from a DataOp node.

    Reads from the node's internal results cache (populated by a prior
    _evaluate_and_cache_all_nodes call), falling back to .skb.preview().
    Never calls .skb.eval() -- avoids re-executing the pipeline per node.
    """
    try:
        # 1. Check the internal results cache (populated by single-pass evaluate)
        impl = getattr(node_obj, "_skrub_impl", None)
        if impl is not None:
            cached = getattr(impl, "results", {}).get("fit_transform")
            if cached is not None:
                df = _to_dataframe(cached)
                if df is not None:
                    result = _dataframe_to_preview_dict(df, node_id)
                    if result:
                        return result

        # 2. Fall back to .skb.preview() (reads "preview" mode cache)
        skb = getattr(node_obj, "skb", None)
        if skb is None:
            return None
        preview_func = getattr(skb, "preview", None)
        if callable(preview_func):
            try:
                df = _to_dataframe(preview_func())
                if df is not None:
                    return _dataframe_to_preview_dict(df, node_id)
            except Exception:
                pass

        return None
    except Exception as e:
        print(f"Warning: Could not get preview for node {node_id}: {e}", file=sys.stderr)
        return None


def _extract_previews_from_capture(raw_graph):
    """Build node preview list from _captured_previews (populated during exec).

    Matches raw_graph node objects by Python id() to summaries captured during the
    evaluate() callback. Returns same format as _extract_all_previews.
    No additional pipeline evaluation is needed.
    """
    if not raw_graph or not isinstance(raw_graph, dict):
        return []

    node_list = _nodes_to_list(raw_graph.get("nodes") or [])

    previews = []
    for i, node_obj in enumerate(node_list):
        node_id = str(i)
        summary = _captured_previews.get(id(node_obj))
        if summary:
            previews.append({"node_id": node_id, **summary})

    print(
        f"Capture-based preview: {len(previews)}/{len(node_list)} nodes",
        file=sys.stderr,
    )
    return previews


def _extract_all_previews(raw_graph):
    """
    Extract preview data for all nodes in the graph.
    Returns list of preview dicts (node_id, schema, sample, row_count).
    Walks every node in raw_graph["nodes"] (handles both list and dict).

    Expects that _evaluate_and_cache_all_nodes was called beforehand so each
    node has its result cached in _skrub_impl.results["fit_transform"].
    """
    if not raw_graph or not isinstance(raw_graph, dict):
        return []

    node_list = _nodes_to_list(raw_graph.get("nodes") or [])

    previews = []
    missing_ids = []
    for i, node_obj in enumerate(node_list):
        node_id = str(i)
        preview = _extract_preview_from_dataop(node_obj, node_id)
        if preview:
            previews.append(preview)
        else:
            missing_ids.append(node_id)

    total = len(node_list)
    got = len(previews)
    if missing_ids:
        print(
            f"Preview extraction: {got}/{total} nodes got previews; "
            f"missing node indices: {missing_ids}",
            file=sys.stderr,
        )
    else:
        print(f"Preview extraction: {got}/{total} nodes got previews (all covered)", file=sys.stderr)

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

    env = _find_env_dict(globals_dict)
    if raw_graph and isinstance(raw_graph, dict) and "nodes" in raw_graph:
        try:
            graph_dict = _graph_to_serializable(raw_graph)
        except Exception:
            pass
        # Previews MUST come from the single pipeline execution.
        # Do NOT call skrub.evaluate() here as a fallback: it can re-run the pipeline.
        # If previews can't be extracted from the one run, we fail the run and surface
        # an error to the user (so they can retry), instead of silently executing twice.
        if not _captured_previews:
            raise RuntimeError(
                "Node previews were not captured during execution (no capture data). "
                "Run is required to execute exactly once; refusing to evaluate again."
            )
        # Fast path: previews were captured during exec's evaluate() callback.
        # make_learner() clones the DataOp before fitting, so captured node IDs
        # belong to the clone, not the original result. Build a graph from the
        # learner's cloned DataOp so node ids match.
        learner_dataop = _find_learner_dataop(globals_dict)
        capture_graph = raw_graph
        if learner_dataop is not None:
            try:
                capture_graph = _Graph().run(learner_dataop)
            except Exception:
                capture_graph = raw_graph
        try:
            previews = _extract_previews_from_capture(capture_graph)
        except Exception:
            previews = []

        # Partial capture is normal: classifier/y/state nodes don't produce
        # DataFrames so they won't appear in _captured_previews. But if ZERO
        # DataFrame-producing nodes matched (captures exist but IDs don't align
        # with any graph node), the clone/original mismatch survived the learner
        # lookup — fail so the user can retry.
        if not previews and _captured_previews:
            raise RuntimeError(
                "Node preview IDs from execution don't match graph nodes. "
                "Execution may have failed mid-run. Please retry."
            )

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


def _try_dataop_to_dataframe(val):
    """If val is a DataOp, materialize to a DataFrame via .skb.preview() or .skb.eval().

    Prefer .skb.preview() so that for a subsample DataOp we get the actual subsampled
    row count (e.g. 50), not the Var's default size from .skb.eval().
    """
    try:
        import pandas as pd
    except ImportError:
        return None
    if not hasattr(val, "skb"):
        return None
    skb = val.skb
    # Prefer preview() so subsample etc. report correct row count
    if hasattr(skb, "preview") and callable(skb.preview):
        try:
            out = skb.preview()
            if isinstance(out, pd.DataFrame):
                return out
        except Exception:
            pass
    if hasattr(skb, "eval") and callable(skb.eval):
        try:
            out = skb.eval()
            if isinstance(out, pd.DataFrame):
                return out
        except Exception:
            pass
    return None


def _extract_var_input_summaries(g: dict) -> list[dict]:
    """
    Extract real data summaries for pipeline input variables after exec().

    Looks in three places. We prefer the materialized pipeline result (DataOp) so that
    when the script does e.g. products = skrub.var(...).skb.subsample(n=50), we report
    row_count 50, not the full dataset size from env or Var default.

    Priority order:
    1. Top-level DataOps (e.g. products = ... .skb.subsample(n=50)) — materialize with
       .skb.eval() so row_count reflects the actual subsampled size.
    2. Pipeline data environment dict — checked under common names: env, env_train, env_test,
       environment, train_env, data_env (first match wins per key, deduped by var_name).
    3. Top-level DataFrame variables in g (plain pandas DataFrames).
    """
    try:
        import pandas as pd
    except ImportError:
        return []

    summaries: list[dict] = []
    seen: set[str] = set()

    # Priority 1: top-level DataOps — materialize so row_count matches subsample / pipeline result
    for var_name, val in g.items():
        if var_name.startswith("_") or not isinstance(var_name, str):
            continue
        df = _try_dataop_to_dataframe(val)
        if df is not None:
            s = _df_to_summary(df, var_name)
            if s:
                summaries.append(s)
                seen.add(var_name)

    # Priority 2: pipeline data environment
    _env_candidate = _find_env_dict(g)
    if _env_candidate is not None:
        for var_name, val in _env_candidate.items():
            if var_name in seen or not isinstance(var_name, str) or var_name.startswith("_"):
                continue
            if isinstance(val, pd.DataFrame):
                s = _df_to_summary(val, var_name)
                if s:
                    summaries.append(s)
                    seen.add(var_name)

    # Priority 3: top-level DataFrame variables in g
    for var_name, val in g.items():
        if var_name in seen or var_name.startswith("_") or not isinstance(var_name, str):
            continue
        if isinstance(val, pd.DataFrame):
            s = _df_to_summary(val, var_name)
            if s:
                summaries.append(s)
                seen.add(var_name)

    return summaries


def _extract_var_previews(code: str, g: dict) -> list[dict]:
    """
    Build preview summaries (var_name, schema, sample, row_count) for each assigned
    variable that holds a DataFrame or DataOp. Used to fill node_data for compile nodes
    via var_producer mapping in the backend.
    """
    try:
        import pandas as pd
    except ImportError:
        return []
    result = []
    for var_name in _assignments_in_order(code):
        if var_name not in g or var_name.startswith("_"):
            continue
        val = g[var_name]
        df = None
        if isinstance(val, pd.DataFrame):
            df = val
        elif _is_dataop(val):
            df = _try_dataop_to_dataframe(val)
        if df is not None:
            s = _df_to_summary(df, var_name)
            if s:
                result.append(s)
    return result


def main():
    t_main_start = time.perf_counter()
    code = sys.stdin.read()

    # Set up capture patch BEFORE preparing globals (which may trigger operator imports).
    # This replaces sempipes.llm.llm.generate_python_code_from_messages before operators see it.
    _setup_capture_patch()

    g = _prepare_globals()
    startup_ms = (time.perf_counter() - t_main_start) * 1000
    exec_failed = False

    # Clear per-operator costs and attempts from any previous run (e.g. if module is reused)
    _per_operator_costs.clear()
    _per_operator_attempts.clear()
    _captured_previews.clear()
    _captured_code_node_refs.clear()

    # Patch evaluate() to capture node previews during exec's pipeline evaluation.
    # This avoids a second evaluate() pass in post-exec for preview extraction.
    # Install once per process; _captured_previews.clear() above handles per-run reset.
    _setup_preview_capture_patch()

    # Track execution time and LLM costs
    # Redirect stdout during exec to suppress noisy sempipes operator output (raw code strings
    # printed directly by operators). All protocol blocks (##SEMPIPES_NODE_CODE##, etc.) are
    # printed after exec completes, so they are unaffected.
    exec_start = time.perf_counter()
    with _track_litellm_costs() as costs:
        try:
            with redirect_stdout(io.StringIO()):
                exec(code, g)
        except Exception:
            exec_failed = True
            traceback.print_exc()  # stderr → merged into runner log
    exec_duration_ms = (time.perf_counter() - exec_start) * 1000
    total_cost_usd = sum(_per_operator_costs)
    t_post_start = time.perf_counter()

    # Emit real data summaries for input variables (from g["env"] or top-level DataFrames).
    # Only emitted when actual data is available — never placeholder/fake data.
    # These feed the UI node details for input nodes (single pipeline run, no extra subprocess).
    input_summaries = _extract_var_input_summaries(g)
    for s in input_summaries:
        print(_NODE_INPUT_SUMMARY_MARKER)
        print(json.dumps(s))
        print(_SKRUB_GRAPH_END)

    # Extract skrub DAG first so we can emit skrub_node_id with each code block (fixes code-to-node mapping).
    graph_dict, svg_str, previews = _get_skrub_dag_dict(code, g)

    # Build capture-idx → graph-node-idx mapping using object references (not id()).
    # Storing actual references (_captured_code_node_refs) prevents GC from freeing the
    # DataOp objects and allowing Python to reuse their memory addresses for new objects,
    # which would cause false id() matches in the graph walk.  The `is` operator gives
    # exact identity — if it matches, the reference is the same object.
    ref_to_graph_idx: dict[int, int] = {}  # capture index → graph node index
    if _captured_code_node_refs:
        try:
            from skrub._data_ops._evaluation import _Graph as _G
            src = _find_learner_dataop(g) or _get_pipeline_result_dataop(code, g)
            if src is not None:
                _raw_for_codes = _G().run(src)
                node_list = _nodes_to_list(_raw_for_codes.get("nodes") or []) if isinstance(_raw_for_codes, dict) else []
                for capture_idx, ref in enumerate(_captured_code_node_refs):
                    if ref is None:
                        continue  # code was generated outside evaluate() — no node context
                    for graph_idx, node in enumerate(node_list):
                        if node is ref:
                            ref_to_graph_idx[capture_idx] = graph_idx
                            break
        except Exception:
            pass

    # Emit captured operator-generated code so backend can emit node_code (no bypass).
    # Only emit codes attributed to semantic display nodes (sempipesNodeIds).  Codes from
    # internal operators (e.g. apply_with_sem_choose's choose_from logic) are silently
    # skipped — they have no corresponding UI slot and must not poison the assignment.
    semantic_node_ids = set(graph_dict.get("sempipesNodeIds") or []) if graph_dict else set()
    capture_to_skrub = _map_captures_to_skrub_semantic_nodes(
        len(_captured_codes), ref_to_graph_idx, semantic_node_ids
    )
    for i in sorted(capture_to_skrub):
        sid = capture_to_skrub[i]
        gi = ref_to_graph_idx.get(i)
        if gi is None or str(gi) != sid:
            print(
                f"SEMPIPES> Code block {i} → skrub node {sid} (order fallback; ref match failed)",
                file=sys.stderr,
            )
    n_dropped = len(_captured_codes) - len(capture_to_skrub)
    if n_dropped > 0 and semantic_node_ids:
        print(
            f"SEMPIPES> Warning: {n_dropped} code capture(s) omitted (could not map to a semantic node)",
            file=sys.stderr,
        )

    for i, code_str in enumerate(_captured_codes):
        ref = _captured_code_node_refs[i] if i < len(_captured_code_node_refs) else None
        skrub_node_id = capture_to_skrub.get(i)
        if skrub_node_id is None:
            continue
        if skrub_node_id not in semantic_node_ids:
            continue

        graph_idx = ref_to_graph_idx.get(i)
        match_method = (
            "ref_is"
            if graph_idx is not None and str(graph_idx) == skrub_node_id
            else "order_fallback"
        )
        debug_info = {
            "match_method": match_method,
            "ref_class": ref.__class__.__name__ if ref is not None else None,
            "node_index": graph_idx,
        }
        cost_usd = _per_operator_costs[i] if i < len(_per_operator_costs) else 0.0
        attempts = _per_operator_attempts[i] if i < len(_per_operator_attempts) else 1
        payload = {
            "index": i,
            "code": code_str,
            "cost_usd": cost_usd,
            "attempts": attempts,
            "debug_info": debug_info,
            "skrub_node_id": skrub_node_id,
        }
        print("##SEMPIPES_NODE_CODE##")
        print(json.dumps(payload))
        print("##END##")
    if graph_dict:
        print(_SKRUB_GRAPH_MARKER)
        print(json.dumps(graph_dict))
        print(_SKRUB_GRAPH_END)
    # Emit node previews (intermediate data for each node)
    for preview in previews:
        print(_NODE_PREVIEW_MARKER)
        print(json.dumps(preview))
        print(_SKRUB_GRAPH_END)

    # Emit var previews (per-assignment DataFrame/DataOp) for backend to map to compile nodes
    for var_preview in _extract_var_previews(code, g):
        print(_VAR_PREVIEW_MARKER)
        print(json.dumps(var_preview))
        print(_SKRUB_GRAPH_END)

    # Data statistics for node details (schema, sample, row_count) are extracted here as part of
    # the single pipeline execution. No separate subprocess is used. The backend parses these
    # blocks and emits input_summary (input nodes) and node_data (operator outputs) for the UI.
    # - NODE_INPUT_SUMMARY: per input variable (var_name, schema, sample, row_count)
    # - NODE_PREVIEW: per graph node from .skb.preview() (node_id, schema, sample, row_count)
    # - VAR_PREVIEW: per variable assignment for backend var_producer → compile node mapping

    post_exec_ms = (time.perf_counter() - t_post_start) * 1000
    # Emit execution stats (duration and cost) plus profiling breakdown
    stats_payload = {
        "duration_ms": exec_duration_ms,
        "cost_usd": total_cost_usd,
        "startup_ms": startup_ms,
        "post_exec_ms": post_exec_ms,
    }
    # Include pipeline metric if set by the script (e.g. _pipeline_metric = {"name": "F1", "value": 0.82})
    metric = g.get("_pipeline_metric")
    if isinstance(metric, dict) and "name" in metric and "value" in metric:
        try:
            stats_payload["metric"] = {"name": str(metric["name"]), "value": float(metric["value"])}
        except (TypeError, ValueError):
            pass
    print(_EXECUTION_STATS_MARKER)
    print(json.dumps(stats_payload))
    print(_SKRUB_GRAPH_END)

    if exec_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
