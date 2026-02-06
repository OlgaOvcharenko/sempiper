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
"""
import json
import re
import sys
import types
import importlib.machinery
import importlib.util

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


def _capturing_generate_code_from_messages(messages):
    """Wrapper that captures generated code and delegates to original function."""
    raw_result = _original_generate_code(messages)
    # Unwrap to get clean Python code (remove markdown fences, etc.)
    clean_result = _unwrap_python_func(raw_result) if _unwrap_python_func else raw_result
    _captured_codes.append(clean_result)
    return raw_result  # Return raw result so generate_python_code_from_messages can unwrap it again


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
    if low in ("apply_with_sem_choose", "sem_choose", "apply"):
        return True
    # Skrub labels Apply nodes as "Apply <Estimator>" (e.g. Apply ImputedLearner, Apply LLMImputer).
    if low.startswith("apply "):
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

    n = len(node_list)
    parents = {}
    children = {}
    for i in range(n):
        si = str(i)
        node_ref = node_list[i] if i < len(node_list) else i
        p = parents_raw.get(i) or parents_raw.get(node_ref, [])
        c = children_raw.get(i) or children_raw.get(node_ref, [])
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


def _get_skrub_dag_dict(code, globals_dict):
    """
    Get skrub DAG as a serializable dict using _Graph().run(result) and native SVG from draw_graph().
    Returns (graph_dict, svg_str). graph_dict for interactive DAG; svg_str for native skrub SVG (saved to disk).
    """
    result = _get_pipeline_result_dataop(code, globals_dict)
    if result is None:
        return None, None

    graph_dict = None
    svg_str = None

    # Try _Graph().run() for interactive DAG
    try:
        from skrub._data_ops._evaluation import _Graph
        raw = _Graph().run(result)
        if raw and isinstance(raw, dict) and "nodes" in raw:
            graph_dict = _graph_to_serializable(raw)
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

    return graph_dict, svg_str


def main():
    code = sys.stdin.read()

    # Set up capture patch BEFORE preparing globals (which may trigger operator imports).
    # This replaces sempipes.llm.llm.generate_python_code_from_messages before operators see it.
    _setup_capture_patch()

    g = _prepare_globals()
    exec_failed = False
    try:
        exec(code, g)
    except Exception:
        exec_failed = True

    # Emit captured operator-generated code so backend can emit node_code (no bypass).
    for i, code_str in enumerate(_captured_codes):
        print("##SEMPIPES_NODE_CODE##")
        print(json.dumps({"index": i, "code": code_str}))
        print("##END##")

    # Extract skrub DAG as dict (_Graph().run) and native SVG (draw_graph)
    graph_dict, svg_str = _get_skrub_dag_dict(code, g)
    if graph_dict:
        print(_SKRUB_GRAPH_MARKER)
        print(json.dumps(graph_dict))
        print(_SKRUB_GRAPH_END)
    if svg_str:
        # Emit native skrub SVG for saving to disk (backend replaces by script name)
        print(_SKRUB_GRAPH_SVG_MARKER)
        print(svg_str, end="")
        print("\n" + _SKRUB_GRAPH_END)

    if exec_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
