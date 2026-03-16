"""
Pipeline execution: yield SSE events (terminal output, per-node generated code, cost).
We run the user's pipeline in a subprocess (skrub_graph_runner). Operator-generated code
comes from that run (runner captures sempipes.llm.generate_python_code_from_messages);
we parse ##SEMPIPES_NODE_CODE## blocks from stdout. We do not call the LLM directly.
If we get skrub's computational graph (DataOp.skb.draw_graph) we emit skrub_graph.
Cost is tracked only when LLM is called in-process (subprocess LLM calls are not tracked).
"""
import concurrent.futures
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time

from services.compile_parse import extract_nodes_with_ranges, get_var_producer
from services.data_summary_extractor import get_data_summary

logger = logging.getLogger(__name__)


def _sse(data: dict) -> bytes:
    """Serialize an SSE event dict, injecting a wall-clock timestamp (Unix ms)."""
    data["ts_ms"] = int(time.time() * 1000)
    return f"data: {json.dumps(data)}\n\n".encode()


# Backend root (demo/backend) so -m services.skrub_graph_runner resolves when cwd is set.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Directory for saved skrub native SVG graphs (demo/graph_svgs/), keyed by script id.
_GRAPH_SVGS_DIR = os.path.join(os.path.dirname(_BACKEND_ROOT), "graph_svgs")

# Marker and format emitted by skrub_graph_runner for each operator-generated code block.
_SEMPIPES_NODE_CODE_MARKER = "##SEMPIPES_NODE_CODE##"
_SEMPIPES_NODE_CODE_END = "##END##"
_SKRUB_GRAPH_MARKER = "##SKRUB_GRAPH##"
_SKRUB_GRAPH_END = "##END##"
_SKRUB_GRAPH_SVG_MARKER = "##SKRUB_GRAPH_SVG##"
_NODE_PREVIEW_MARKER = "##NODE_PREVIEW##"
_VAR_PREVIEW_MARKER = "##VAR_PREVIEW##"
_EXECUTION_STATS_MARKER = "##EXECUTION_STATS##"
_NODE_INPUT_SUMMARY_MARKER = "##NODE_INPUT_SUMMARY##"


def _parse_captured_codes_from_stdout(stdout_str: str) -> list[dict]:
    """
    Parse ##SEMPIPES_NODE_CODE##\\n{json}\\n##END## blocks from runner stdout.
    Returns list of dicts with "code", "cost_usd", "attempts", and optionally "skrub_node_id".
    """
    by_index: dict[int, dict] = {}
    pattern = re.compile(
        re.escape(_SEMPIPES_NODE_CODE_MARKER) + r"\s*\n([^\n]+)\n" + re.escape(_SEMPIPES_NODE_CODE_END)
    )
    for m in pattern.finditer(stdout_str):
        try:
            obj = json.loads(m.group(1))
            idx = obj.get("index", len(by_index))
            code = obj.get("code", "")
            code_str = code if isinstance(code, str) else str(code)
            cost_usd = float(obj.get("cost_usd", 0.0)) if isinstance(obj.get("cost_usd"), (int, float)) else 0.0
            raw_attempts = obj.get("attempts", obj.get("retries", 1))
            attempts = max(1, int(raw_attempts)) if isinstance(raw_attempts, (int, float)) else 1
            entry: dict = {"code": code_str, "cost_usd": cost_usd, "attempts": attempts}
            skrub_id = obj.get("skrub_node_id")
            if skrub_id is not None and isinstance(skrub_id, str) and skrub_id.strip():
                entry["skrub_node_id"] = str(skrub_id).strip()
            by_index[idx] = entry
        except (json.JSONDecodeError, TypeError):
            continue
    return [by_index[i] for i in sorted(by_index)]


def _parse_skrub_graph_from_stdout(stdout_str: str) -> dict | None:
    """
    Parse ##SKRUB_GRAPH##\\n{json}\\n##END## block from runner stdout.
    Returns graph dict with keys nodes, parents, children, or None.
    """
    # Use non-greedy (.*?) so we stop at the FIRST ##END## (not the last one)
    pattern = re.compile(
        re.escape(_SKRUB_GRAPH_MARKER) + r"\s*\n(.*?)\n" + re.escape(_SKRUB_GRAPH_END),
        re.DOTALL,
    )
    m = pattern.search(stdout_str)
    if not m:
        return None
    try:
        blob = m.group(1).strip()
        obj = json.loads(blob)
        if isinstance(obj, dict) and "nodes" in obj:
            return obj
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _parse_skrub_svg_from_stdout(stdout_str: str) -> str | None:
    """
    Parse ##SKRUB_GRAPH_SVG##\\n{svg}\\n##END## block from runner stdout.
    Returns the native skrub SVG string, or None.
    """
    pattern = re.compile(
        re.escape(_SKRUB_GRAPH_SVG_MARKER) + r"\s*\n(.*?)\n" + re.escape(_SKRUB_GRAPH_END),
        re.DOTALL,
    )
    m = pattern.search(stdout_str)
    if not m:
        return None
    svg = m.group(1).strip()
    if svg.startswith("<svg") and "</svg>" in svg:
        return svg
    return None


def _parse_node_previews_from_stdout(stdout_str: str) -> list[dict]:
    """
    Parse ##NODE_PREVIEW##\\n{json}\\n##END## blocks from runner stdout.
    Returns list of preview dicts with node_id, schema, sample, row_count.
    """
    previews: list[dict] = []
    pattern = re.compile(
        re.escape(_NODE_PREVIEW_MARKER) + r"\s*\n([^\n]+)\n" + re.escape(_SKRUB_GRAPH_END)
    )
    for m in pattern.finditer(stdout_str):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "node_id" in obj:
                previews.append(obj)
        except (json.JSONDecodeError, TypeError):
            continue
    return previews


def _parse_var_previews_from_stdout(stdout_str: str) -> list[dict]:
    """
    Parse ##VAR_PREVIEW##\\n{json}\\n##END## blocks from runner stdout.
    Returns list of dicts with var_name, schema, sample, row_count.
    """
    previews: list[dict] = []
    pattern = re.compile(
        re.escape(_VAR_PREVIEW_MARKER) + r"\s*\n([^\n]+)\n" + re.escape(_SKRUB_GRAPH_END)
    )
    for m in pattern.finditer(stdout_str):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "var_name" in obj:
                previews.append(obj)
        except (json.JSONDecodeError, TypeError):
            continue
    return previews


def _build_static_to_dynamic_id(static_nodes: list, runnable: list) -> dict[str, str]:
    """
    Map static parse node IDs to display (dynamic) node IDs by matching (label, index).
    Used to emit node_data for VAR_PREVIEW under the compile node ID the frontend shows.
    """
    if not static_nodes or not runnable:
        return {}
    # Static: sort by source line, group by label
    def static_sort_key(n):
        sr = getattr(n, "source_range", None)
        return (sr.start_line, sr.start_column) if sr else (999999, 0)

    static_by_label: dict[str, list[str]] = {}
    for n in sorted(static_nodes, key=static_sort_key):
        label = (getattr(n, "label", "") or "").lower()
        nid = getattr(n, "id", str(n))
        if label not in static_by_label:
            static_by_label[label] = []
        static_by_label[label].append(nid)
    # Dynamic/runnable: sort by id (numeric if possible), group by label
    def dynamic_sort_key(n):
        i = getattr(n, "id", str(n))
        try:
            return (0, int(i))
        except (ValueError, TypeError):
            return (1, i)

    dynamic_by_label: dict[str, list[str]] = {}
    for n in sorted(runnable, key=dynamic_sort_key):
        label = (getattr(n, "label", "") or "").lower()
        nid = getattr(n, "id", str(n))
        if label not in dynamic_by_label:
            dynamic_by_label[label] = []
        dynamic_by_label[label].append(nid)
    # For each label, map i-th static to i-th dynamic
    result: dict[str, str] = {}
    for label, static_ids in static_by_label.items():
        dynamic_ids = dynamic_by_label.get(label, [])
        for i, static_id in enumerate(static_ids):
            if i < len(dynamic_ids):
                result[static_id] = dynamic_ids[i]
    return result


def _parse_execution_stats_from_stdout(stdout_str: str) -> dict | None:
    """
    Parse ##EXECUTION_STATS##\\n{json}\\n##END## block from runner stdout.
    Returns dict with duration_ms and cost_usd, or None.
    """
    pattern = re.compile(
        re.escape(_EXECUTION_STATS_MARKER) + r"\s*\n([^\n]+)\n" + re.escape(_SKRUB_GRAPH_END)
    )
    m = pattern.search(stdout_str)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _parse_node_input_summaries_from_stdout(stdout_str: str) -> dict[str, dict]:
    """
    Parse ##NODE_INPUT_SUMMARY##\\n{json}\\n##END## blocks from runner stdout.
    Returns dict keyed by var_name -> {schema, sample, row_count}.
    Only real data is emitted by the runner; no placeholders are expected.
    """
    result: dict[str, dict] = {}
    pattern = re.compile(
        re.escape(_NODE_INPUT_SUMMARY_MARKER) + r"\s*\n([^\n]+)\n" + re.escape(_SKRUB_GRAPH_END)
    )
    for m in pattern.finditer(stdout_str):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "var_name" in obj and "schema" in obj:
                var_name = obj["var_name"]
                result[var_name] = {
                    "schema": obj["schema"],
                    "sample": obj.get("sample", []),
                    "row_count": obj.get("row_count", 0),
                }
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def _merge_compile_inputs_into_skrub_graph(
    skrub_graph: dict, compile_nodes: list, compile_edges: list
) -> dict:
    """
    Prepend compile input nodes (and any missing upstream operators) to the skrub graph
    so the displayed DAG is full (inputs -> operators -> outputs). Skrub may omit Var/subsample.
    """
    runnable = [n for n in compile_nodes if getattr(n, "type", "").lower() in ("input", "operator")]
    if not runnable:
        return skrub_graph
    skrub_labels = {n.get("label", "") for n in (skrub_graph.get("nodes") or [])}
    # Find compile nodes missing from skrub, in compile order
    missing: list = []
    for n in runnable:
        label = getattr(n, "label", n.id) or str(n.id)
        if label not in skrub_labels:
            missing.append(n)
    if not missing:
        return skrub_graph
    # Build id mapping for compile nodes: runnable index -> new id for missing nodes
    existing_ids = {sn.get("id") for sn in (skrub_graph.get("nodes") or []) if sn.get("id")}
    prefix = "in_"
    next_idx = 0
    def new_id():
        nonlocal next_idx
        while f"{prefix}{next_idx}" in existing_ids:
            next_idx += 1
        sid = f"{prefix}{next_idx}"
        existing_ids.add(sid)
        next_idx += 1
        return sid
    # Add missing nodes at the front; wire last missing -> first skrub root
    skrub_nodes = list(skrub_graph.get("nodes") or [])
    parents = dict(skrub_graph.get("parents") or {})
    children = dict(skrub_graph.get("children") or {})
    sempipes_node_ids = list(skrub_graph.get("sempipesNodeIds") or [])
    id_to_idx = {getattr(n, "id", n): i for i, n in enumerate(runnable)}
    # Edges: (src_id, tgt_id) from compile
    compile_edge_pairs = set()
    for e in compile_edges:
        src, tgt = getattr(e, "source", None), getattr(e, "target", None)
        if src and tgt and src in id_to_idx and tgt in id_to_idx:
            compile_edge_pairs.add((src, tgt))
    # Map compile node id -> new skrub id for missing nodes
    missing_ids: dict[str, str] = {}
    new_nodes: list[dict] = []
    for n in missing:
        nid = new_id()
        missing_ids[n.id] = nid
        label = getattr(n, "label", n.id) or str(n.id)
        t = (getattr(n, "type", "") or "").lower()
        is_sem = t == "operator" and _is_semantic_operator(label)
        new_nodes.append({"id": nid, "label": label, "is_sempipes_semantic": is_sem})
        parents[nid] = []
        children[nid] = []
    # Wire edges among missing nodes
    for src, tgt in compile_edge_pairs:
        if src in missing_ids and tgt in missing_ids:
            si, ti = missing_ids[src], missing_ids[tgt]
            if ti not in children.get(si, []):
                children.setdefault(si, []).append(ti)
                parents.setdefault(ti, []).append(si)
    # Find skrub roots (nodes with no parents)
    skrub_root_ids = [sn["id"] for sn in skrub_nodes if not (parents.get(sn["id"]) or [])]
    # Connect last missing node to first skrub root (by compile order)
    if missing and skrub_root_ids:
        last_missing = missing[-1]
        # Find first skrub node that consumes last_missing's output (from compile edges)
        last_id = last_missing.id
        first_skrub_consumer = None
        for src, tgt in compile_edge_pairs:
            if src == last_id and tgt in id_to_idx:
                tgt_node = runnable[id_to_idx[tgt]]
                tgt_label = getattr(tgt_node, "label", tgt_node.id)
                for sn in skrub_nodes:
                    if sn.get("label") == tgt_label:
                        first_skrub_consumer = sn["id"]
                        break
                break
        if first_skrub_consumer is None:
            first_skrub_consumer = skrub_root_ids[0]
        if last_id in missing_ids:
            si = missing_ids[last_id]
            if first_skrub_consumer not in children.get(si, []):
                children.setdefault(si, []).append(first_skrub_consumer)
                parents.setdefault(first_skrub_consumer, []).append(si)
    # Prepend new nodes
    merged_nodes = new_nodes + skrub_nodes
    return {
        "nodes": merged_nodes,
        "parents": parents,
        "children": children,
        "sempipesNodeIds": sempipes_node_ids,
    }


def _build_fallback_graph_from_compile(
    nodes: list, edges: list
) -> dict | None:
    """
    Build a SkrubGraphDict-shaped dict from compile nodes/edges when the runner
    did not produce ##SKRUB_GRAPH## (e.g. _Graph().run failed, fell back to SVG).
    Ensures the user always sees a graph after Run.
    """
    runnable = [n for n in nodes if getattr(n, "type", "").lower() in ("input", "operator")]
    if not runnable:
        return None
    node_ids = [n.id for n in runnable]
    id_to_idx = {nid: str(i) for i, nid in enumerate(node_ids)}
    skrub_nodes = []
    parents: dict[str, list[str]] = {str(i): [] for i in range(len(node_ids))}
    children: dict[str, list[str]] = {str(i): [] for i in range(len(node_ids))}
    sempipes_node_ids: list[str] = []
    for i, n in enumerate(runnable):
        nid = str(i)
        t = (getattr(n, "type", "") or "").lower()
        label = getattr(n, "label", n.id) or str(n.id)
        is_sem = t == "operator" and _is_semantic_operator(label)
        skrub_nodes.append({"id": nid, "label": label, "is_sempipes_semantic": is_sem})
        if is_sem:
            sempipes_node_ids.append(nid)
    for e in edges:
        src = getattr(e, "source", None)
        tgt = getattr(e, "target", None)
        if src in id_to_idx and tgt in id_to_idx:
            si, ti = id_to_idx[src], id_to_idx[tgt]
            if si != ti and ti not in children.get(si, []):
                children[si].append(ti)
                parents[ti].append(si)
    return {
        "nodes": skrub_nodes,
        "parents": parents,
        "children": children,
        "sempipesNodeIds": sempipes_node_ids,
    }


def _build_skrub_to_compile_id(graph: dict, runnable: list) -> dict[str, str]:
    """
    Build mapping from runtime skrub node IDs to static compile node IDs.

    WHY THIS MAPPING EXISTS:
    ───────────────────────────────────────────────────────────────────────────────
    - Skrub graph (runtime) has numeric IDs: "0", "1", "2"
    - Compile nodes (static parsing) have semantic IDs: "var_products_4", "subsample_5"
    - Frontend may need to map between these for debugging or backward compatibility
    - Sent to frontend in skrubToCompileId field of skrub_graph event

    MATCHING STRATEGY:
    ───────────────────────────────────────────────────────────────────────────────
    - Match by label ONLY (not by position/index)
    - Skrub graph node order (topological from _Graph().run()) may differ from document order
    - For nodes with same label, match Nth occurrence in runtime graph to Nth occurrence
      in compile nodes (sorted by source_range.start_line for document order)

    SPECIAL CASES:
    ───────────────────────────────────────────────────────────────────────────────
    - GetItem nodes in skrub → as_X/as_y nodes in compile (sempipes.as_X(df[cols]) creates GetItem)
    - Mapping is best-effort; mismatches possible if labels are ambiguous or change between runs

    CRITICAL: This mapping is ESSENTIAL for dynamic compilation! Runtime and compile-time
    graphs have DIFFERENT numeric IDs (separate runs). Frontend needs this to display generated code.
    """
    if not graph or not runnable:
        return {}
    nodes = graph.get("nodes") or []
    result: dict[str, str] = {}

    # Sort runnable by document order (source_range.start_line) to ensure correct matching
    sorted_runnable = sorted(
        runnable,
        key=lambda n: getattr(n, "source_range", None).start_line
        if getattr(n, "source_range", None)
        else 999999,
    )

    # Build label -> list of compile node ids mapping (in document order)
    label_to_compile_ids: dict[str, list[str]] = {}
    for n in sorted_runnable:
        label = (getattr(n, "label", "") or "").lower()
        node_id = getattr(n, "id", str(n))
        if label not in label_to_compile_ids:
            label_to_compile_ids[label] = []
        label_to_compile_ids[label].append(node_id)

    # Build reverse mapping for as_X and as_y (we'll use these for GetItem mapping)
    as_x_ids = label_to_compile_ids.get("as_x", [])
    as_y_ids = label_to_compile_ids.get("as_y", [])
    as_x_usage = 0
    as_y_usage = 0

    # Build mapping for pandas operations that might have chained methods
    groupby_ids = label_to_compile_ids.get("groupby", [])
    groupby_usage = 0

    # Track which occurrence of each label we've used
    label_usage: dict[str, int] = {}

    # Track the last mapped node for chained operations
    last_mapped_id: str | None = None

    # Match by label, handling duplicates by tracking occurrences
    for sn in nodes:
        skid = sn.get("id")
        if not skid:
            continue
        label = (sn.get("label", "") or "").lower()

        # Special case: Map GetItem nodes to as_X/as_y nodes
        # GetItem nodes are created by skrub for df[cols] operations inside as_X/as_y
        if label.startswith("<getitem"):
            # Try to map to as_X first, then as_y
            if as_x_usage < len(as_x_ids):
                result[skid] = as_x_ids[as_x_usage]
                last_mapped_id = as_x_ids[as_x_usage]
                as_x_usage += 1
                continue
            elif as_y_usage < len(as_y_ids):
                result[skid] = as_y_ids[as_y_usage]
                last_mapped_id = as_y_ids[as_y_usage]
                as_y_usage += 1
                continue

        # Special case: Map pandas chained methods to their parent operation
        # e.g., .agg() and .reset_index() after .groupby() should map to groupby node
        if label in ("<callmethod 'agg'>", "<callmethod 'reset_index'>", "<callmethod 'mean'>", "<callmethod 'sum'>"):
            # If we have a groupby node and haven't used it yet, map to it
            if groupby_usage < len(groupby_ids):
                result[skid] = groupby_ids[groupby_usage]
                last_mapped_id = groupby_ids[groupby_usage]
                # Don't increment groupby_usage - allow multiple chained methods to map to same groupby
                continue
            # Otherwise, map to the last mapped node if available
            elif last_mapped_id:
                result[skid] = last_mapped_id
                continue

        occurrence = label_usage.get(label, 0)
        compile_ids = label_to_compile_ids.get(label, [])

        if occurrence < len(compile_ids):
            result[skid] = compile_ids[occurrence]
            last_mapped_id = compile_ids[occurrence]
            label_usage[label] = occurrence + 1
            # Track groupby usage for chained methods
            if label == "groupby":
                groupby_usage += 1

    # Extend so every runtime node maps to a compile ID (for node_data lookups in the UI).
    # 1) Map runtime node id to self when it's also a compile node id (e.g. 12 -> 12).
    # 2) For unmapped nodes, use the compile ID of the nearest ancestor that is mapped.
    result = _extend_skrub_to_compile_id(graph, result, runnable)
    return result


def _extend_skrub_to_compile_id(
    graph: dict, base_mapping: dict[str, str], runnable: list
) -> dict[str, str]:
    """
    Extend base_mapping so every node in the runtime graph has a compile ID.
    - If a graph node id equals a compile node id, map it to itself.
    - Otherwise, map unmapped nodes to the compile ID of their nearest mapped ancestor.
    """
    if not graph or not runnable:
        return dict(base_mapping)
    compile_ids = {getattr(n, "id", str(n)) for n in runnable}
    extended = dict(base_mapping)
    nodes = graph.get("nodes") or []
    all_skrub_ids = {sn.get("id") for sn in nodes if sn.get("id")}
    # Also include ids from children/parents in case they're not in nodes
    children = graph.get("children") or {}
    parents = graph.get("parents") or {}
    for pid, cids in children.items():
        all_skrub_ids.add(pid)
        all_skrub_ids.update(cids)
    for cid, pids in parents.items():
        all_skrub_ids.add(cid)
        all_skrub_ids.update(pids)
    # Build parent_of: one parent per node (first parent from "parents" or from "children")
    parent_of: dict[str, str] = {}
    for node_id, parent_list in parents.items():
        if parent_list:
            parent_of[node_id] = parent_list[0]
    for parent_id, child_list in children.items():
        for child_id in child_list:
            if child_id not in parent_of:
                parent_of[child_id] = parent_id
    # 1) Identity for graph nodes that are compile node ids
    for skid in all_skrub_ids:
        if skid and skid not in extended and skid in compile_ids:
            extended[skid] = skid
    # 2) Unmapped nodes: assign compile ID of nearest mapped ancestor
    for skid in all_skrub_ids:
        if not skid or skid in extended:
            continue
        current: str | None = skid
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            if current in extended:
                extended[skid] = extended[current]
                break
            current = parent_of.get(current)
        # If we never found a mapped ancestor, leave unmapped (no change from base)
    return extended


def _is_semantic_operator(label: str) -> bool:
    """
    Return True if this operator generates code via LLM.
    Matches logic from skrub_graph_runner._is_sempipes_semantic_label.

    Semantic operators (code-generating):
    - sem_* operators (sem_fillna, sem_gen_features, etc.)
    - apply_with_sem_choose, sem_choose, apply
    - Apply nodes from skrub (label starts with "apply ")

    Non-semantic operators (data operations only):
    - skb.subsample, skb.eval, etc.
    """
    if not label:
        return False
    low = label.strip().lower()
    if low.startswith("sem_"):
        return True
    if low in ("apply_with_sem_choose", "sem_choose"):
        return True
    return False


def _mock_generated_code_for_node(node_id: str, label: str, node_type: str) -> str:
    """Return placeholder code when no captured code from pipeline run (demo fallback)."""
    if node_type == "input":
        return f"# Input: {label}\n# node_id = {node_id}\ndata = load_input()"
    return (
        "# [Placeholder — no code captured from pipeline run; run with sempipes + API key for real code]\n"
        f"# Node: {label} ({node_id})\n"
        "def step(data):\n"
        "    # Replace with actual generated code when pipeline runs and operators call LLM.\n"
        "    return data"
    )


def _sanitize_svg_for_save(svg: str) -> str:
    """Remove any trailing ##END## or runner markers that may have been captured."""
    s = svg.strip()
    if s.endswith("##END##"):
        s = s[: -len("##END##")].strip()
    if s.endswith("\n##END##"):
        s = s[: -len("\n##END##")].strip()
    return s


def _extract_single_svg_document(s: str) -> str:
    """Return the first complete SVG document (first <svg to last </svg> inclusive), or original if not found."""
    start = s.find("<svg")
    if start < 0:
        return s
    end_tag = "</svg>"
    end = s.rfind(end_tag)
    if end < 0 or end < start:
        return s
    return s[start : end + len(end_tag)]


def _save_skrub_svg_to_cache(svg: str, cache_key: str | None) -> None:
    """Save native skrub SVG to cache."""
    if not cache_key or not svg:
        return
    svg = _sanitize_svg_for_save(svg)
    svg = _extract_single_svg_document(svg)
    if not svg.startswith("<svg") or "</svg>" not in svg:
        return
    try:
        from services.cache import cache_service, CacheFormat
        cache_service.set(cache_key, "svg", {"svg": svg}, format=CacheFormat.SVG)
        logger.info(f"Saved skrub SVG to cache (key: {cache_key[:8]}...)")
    except Exception as e:
        logger.warning(f"Could not save SVG to cache: {e}")


def stream_execute_events(
    input_code: str,
    script_id: str | None = None,
    llm_name: str | None = None,
    temperature: float | None = None,
    cache_key: str | None = None,
):
    """
    Yield SSE-formatted events: terminal, node_code (from pipeline run), input_summary, skrub_graph, cost, done.
    Operator-generated code comes from running the pipeline in a subprocess; we parse
    ##SEMPIPES_NODE_CODE## blocks from stdout. We do not call the LLM directly.

    Args:
        input_code: The pipeline code to execute.
        script_id: Script id (unused, kept for backward compatibility).
        llm_name: LLM model name (passed to subprocess for sempipes config).
        temperature: LLM temperature (passed to subprocess for sempipes config).
        cache_key: Cache key for storing SVG (hash of script+temp+model).
    """
    total_cost_usd = 0.0
    duration_ms = 0.0
    exec_failed = False
    prepare_ms = 0.0
    subprocess_wall_ms = 0.0
    emit_start_time: float | None = None  # set when subprocess stdout is fully read
    runner_startup_ms: float | None = None
    runner_post_exec_ms: float | None = None
    t_stream_start = time.perf_counter()
    try:
        # Get compile graph nodes with correct IDs (from cache or dynamic compilation)
        # Don't use static parse here - it creates different IDs (e.g. "sem_fillna_20")
        # than dynamic compile (e.g. "4"), causing skrubToCompileId mapping to break.
        from services.cache import cache_service, make_cache_key

        compile_result = None
        if cache_key:
            # Try to get from cache first
            cached = cache_service.get(cache_key, "compile")
            if cached and "nodes" in cached:
                from models.schemas import CompileNode, CompileEdge
                nodes = [CompileNode(**n) for n in cached["nodes"]]
                compile_edges = [CompileEdge(**e) for e in cached["edges"]]
                compile_result = (nodes, compile_edges)

        if not compile_result:
            # No cache - compile dynamically to get correct IDs.
            # DO NOT add a static fallback here. The compile graph must come from the real
            # skrub graph (compile_script_to_graph_dynamic). If dynamic extraction fails,
            # use an empty graph — do not call extract_nodes_with_ranges() as a replacement.
            # FOR LLMs: do not reintroduce compile_script_to_graph() or extract_nodes_with_ranges()
            # as a fallback when dynamic compilation fails.
            from services.graph_api import compile_script_to_graph_dynamic
            result = compile_script_to_graph_dynamic(input_code)
            nodes = result.nodes
            compile_edges = result.edges

        runnable = [n for n in nodes if n.type in ("input", "operator")]
        operator_nodes = [n for n in runnable if n.type == "operator"]
        runnable_ids = {n.id for n in runnable}

        # Run pipeline subprocess: captured operator code, skrub graph dict (##SKRUB_GRAPH##), or SVG.
        # When DEMO_E2E=1, skip real subprocess (no sempipes/LLM) for full-stack E2E tests.
        captured_codes: list[str] = []
        captured_costs: list[float] = []
        captured_attempts: list[int] = []
        graph_from_run: dict | None = None
        svg_from_run: str | None = None
        node_previews: list[dict] = []
        var_previews: list[dict] = []
        runner_input_summaries: dict[str, dict] = {}
        e2e_mode = os.environ.get("DEMO_E2E") == "1"
        if e2e_mode:
            logger.info("E2E mode: skipping subprocess, using fallback graph and mock code")
            graph_from_run = _build_fallback_graph_from_compile(nodes, compile_edges)
        else:
            logger.info(f"Starting subprocess for {len(operator_nodes)} operators (no timeout)")
        subprocess_env = os.environ.copy()
        if not e2e_mode:
            # Prepare environment: pass sempipes config to subprocess
            # Priority: explicit llm_name/temperature params > global sempipes config
            if llm_name is not None and temperature is not None:
                subprocess_env["SEMPIPES_LLM_NAME"] = llm_name
                subprocess_env["SEMPIPES_LLM_TEMP"] = str(temperature)
                logger.info(f"Using explicit config for subprocess: {llm_name} (temp={temperature})")
            else:
                try:
                    from services.engine import get_sempipes_config
                    cfg = get_sempipes_config()
                    if cfg and "llm_for_code_generation" in cfg:
                        llm_cfg = cfg["llm_for_code_generation"]
                        subprocess_env["SEMPIPES_LLM_NAME"] = llm_cfg.get("name", "")
                        temp = llm_cfg.get("parameters", {}).get("temperature", 0.0)
                        subprocess_env["SEMPIPES_LLM_TEMP"] = str(temp)
                        logger.info(f"Passing sempipes config to subprocess: {llm_cfg.get('name')} (temp={temp})")
                except Exception as e:
                    logger.warning(f"Could not get sempipes config for subprocess: {e}")
        
        if not e2e_mode:
            t_before_popen = time.perf_counter()
            prepare_ms = (t_before_popen - t_stream_start) * 1000
            try:
                t_subprocess_start = time.perf_counter()
                proc = subprocess.Popen(
                    [sys.executable, "-m", "services.skrub_graph_runner"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=_BACKEND_ROOT,
                    env=subprocess_env,  # Pass environment with sempipes config
                    text=False,
                )
                logger.info(f"Subprocess started, PID: {proc.pid}")
                stdout_chunks: list[bytes] = []

                def read_stdout():
                    for chunk in iter(proc.stdout.readline, b""):
                        stdout_chunks.append(chunk)
                        try:
                            print(chunk.decode("utf-8", errors="replace"), end="", file=sys.stdout, flush=True)
                        except Exception:
                            pass

                reader = threading.Thread(target=read_stdout, daemon=True)
                reader.start()
                try:
                    proc.stdin.write(input_code.encode("utf-8"))
                    proc.stdin.close()
                    # Run proc.wait() in a thread so GeneratorExit (client disconnect) propagates
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        wait_future = pool.submit(proc.wait)
                        try:
                            while not wait_future.done():
                                yield b""  # checkpoint: allows GeneratorExit to be thrown here
                                time.sleep(0.05)
                        except GeneratorExit:
                            logger.info(f"Client disconnected, killing subprocess PID: {proc.pid}")
                            proc.kill()
                            try:
                                wait_future.result(timeout=2.0)
                            except Exception:
                                pass
                            raise  # close this generator
                finally:
                    reader.join(timeout=1.0)
                t_subprocess_end = time.perf_counter()
                subprocess_wall_ms = (t_subprocess_end - t_subprocess_start) * 1000
                emit_start_time = t_subprocess_end
                decoded = b"".join(stdout_chunks).decode("utf-8", errors="replace")
                captured = _parse_captured_codes_from_stdout(decoded)
                captured_codes = [x["code"] for x in captured]
                captured_costs = [x["cost_usd"] for x in captured]
                captured_attempts = [x["attempts"] for x in captured]
                logger.info(f"Subprocess returncode: {proc.returncode}, stdout: {len(decoded)} chars, captured: {len(captured_codes)} blocks")
                if len(decoded) > 0:
                    logger.info(f"Stdout preview: {decoded[:200]}")
                # Check for subprocess failure
                exec_failed = (proc.returncode != 0)
                # Data statistics for node details come from the runner (single pipeline execution).
                # Parse: ##SKRUB_GRAPH##, ##NODE_PREVIEW##, ##VAR_PREVIEW##, ##NODE_INPUT_SUMMARY##, ##EXECUTION_STATS##.
                if decoded:
                    graph_from_run = _parse_skrub_graph_from_stdout(decoded)
                    svg_from_run = _parse_skrub_svg_from_stdout(decoded)
                    node_previews = _parse_node_previews_from_stdout(decoded)
                    var_previews = _parse_var_previews_from_stdout(decoded)
                    runner_input_summaries = _parse_node_input_summaries_from_stdout(decoded)
                    exec_stats = _parse_execution_stats_from_stdout(decoded)
                    if exec_stats:
                        total_cost_usd = exec_stats.get("cost_usd", 0.0)
                        duration_ms = exec_stats.get("duration_ms", 0.0)
                        runner_startup_ms = exec_stats.get("startup_ms")
                        runner_post_exec_ms = exec_stats.get("post_exec_ms")
                        logger.info(f"Parsed execution stats: duration={duration_ms:.0f}ms, cost=${total_cost_usd:.6f}")
                    logger.info(
                        f"Parsed from runner: {len(runner_input_summaries)} input summaries, "
                        f"{len(node_previews)} node previews, {len(var_previews)} var previews"
                    )
                    if not svg_from_run:
                        idx = decoded.find("<svg")
                        if idx >= 0:
                            extracted = _extract_single_svg_document(decoded[idx:].strip())
                            svg_from_run = extracted if (extracted and extracted.startswith("<svg")) else None
                    if not graph_from_run:
                        graph_from_run = _build_fallback_graph_from_compile(nodes, compile_edges)
                    # Save native skrub SVG to cache
                    if svg_from_run and cache_key:
                        _save_skrub_svg_to_cache(svg_from_run, cache_key)
            except (FileNotFoundError, Exception) as e:
                logger.error(f"Subprocess exception: {type(e).__name__}: {e}")
                exec_failed = True

        # Ensure we have a graph to show when runner returns nothing or fails
        if not graph_from_run and runnable:
            graph_from_run = _build_fallback_graph_from_compile(nodes, compile_edges)

        # Merge compile inputs into skrub graph so we always show a full DAG (inputs -> operators)
        if graph_from_run and runnable:
            graph_from_run = _merge_compile_inputs_into_skrub_graph(
                graph_from_run, nodes, compile_edges
            )

        # When runner emitted skrub_node_id with each code block, use it for correct code-to-node mapping.
        code_by_skrub: dict[str, dict] = {}
        for x in captured:
            sid = x.get("skrub_node_id")
            if sid:
                code_by_skrub[sid] = {"code": x["code"], "cost_usd": x["cost_usd"], "attempts": x["attempts"]}
        skrub_to_compile = _build_skrub_to_compile_id(graph_from_run, runnable) if graph_from_run and runnable else {}
        compile_to_skrub = {v: k for k, v in skrub_to_compile.items()}

        if emit_start_time is None:
            emit_start_time = time.perf_counter()
        yield _sse({'type': 'terminal', 'line': 'Starting pipeline execution...'})
        time.sleep(0.05)

        # Code assignment logic:
        # 1. Primary: Use skrub_node_id from runner (when available)
        # 2. Fallback: Use semantic_op_index to match code to semantic operators only
        #    - semantic_op_index only increments for operators that generate code (sem_*, apply, etc.)
        #    - Non-semantic operators (subsample, eval, etc.) receive mock code
        # 3. Mock: If no code available or non-semantic operator, use placeholder
        #
        # ID CONSISTENCY: When skrub graph is available AND we have valid compile graph, use skrub IDs (from runtime)
        #                 When NO skrub graph OR we fell back to static parse, use compile IDs
        # Check if nodes came from dynamic compile (have numeric IDs like "0", "1") or static parse (have semantic IDs like "as_X_1")
        has_dynamic_compile = nodes and all(n.id.isdigit() for n in nodes if n.id)
        use_skrub_ids = graph_from_run is not None and has_dynamic_compile

        # Track which node IDs have already received node_code events to prevent duplicates
        emitted_node_code_ids: set[str] = set()

        semantic_op_index = 0
        for node in runnable:
            # Use skrub ID when runtime graph is available, compile ID otherwise
            display_id = compile_to_skrub.get(node.id, node.id) if (use_skrub_ids and compile_to_skrub) else node.id
            yield _sse({'type': 'terminal', 'line': f'Running {node.label} ({display_id})...'})
            time.sleep(0.05)

            # Determine if this is a semantic (code-generating) operator
            is_semantic = node.type != "input" and _is_semantic_operator(node.label)

            if node.type == "input":
                # Input nodes: emit real data summary when available.
                # Priority: runner-captured data (from ##NODE_INPUT_SUMMARY##) >
                #           get_data_summary (separate subprocess for vars with inline defaults).
                # Never emit placeholder data.
                var_name = None
                if "<Var '" in node.label:
                    match = re.search(r"<Var '([^']+)'>", node.label)
                    if match:
                        var_name = match.group(1)

                summary = None
                if var_name and var_name in runner_input_summaries:
                    # Best path: runner already evaluated the pipeline and captured real data
                    summary = dict(runner_input_summaries[var_name])
                    summary["node_id"] = display_id
                elif var_name and node.source_range and node.source_range.end_line:
                    # Fallback: run partial script to evaluate vars with inline default values
                    cache_dir = os.path.join(_BACKEND_ROOT, ".cache") if cache_key else None
                    try:
                        summary = get_data_summary(
                            input_code,
                            var_name,
                            node.source_range.end_line,
                            cache_dir=cache_dir
                        )
                        if summary is not None:
                            summary["node_id"] = display_id
                    except Exception as e:
                        logger.warning(f"Failed to get real data summary for {var_name}: {e}")

                if summary is not None:
                    yield _sse({'type': 'input_summary', **summary})
                    time.sleep(0.02)
            elif not is_semantic:
                # Non-semantic operators (subsample, eval, etc.): no input_summary emitted.
                # Their output data is captured as node_data via ##NODE_PREVIEW## blocks.
                pass
            else:
                # Semantic operators: emit generated code
                skid = compile_to_skrub.get(node.id) if compile_to_skrub else None
                if skid is not None and skid in code_by_skrub:
                    # Primary path: use skrub_node_id mapping
                    code = code_by_skrub[skid]["code"]
                    node_cost = code_by_skrub[skid]["cost_usd"]
                    node_retries = code_by_skrub[skid]["attempts"]
                    is_fallback = False
                elif semantic_op_index < len(captured_codes):
                    # Fallback: use semantic operator index
                    code = captured_codes[semantic_op_index]
                    node_cost = captured_costs[semantic_op_index] if semantic_op_index < len(captured_costs) else 0.0
                    node_retries = captured_attempts[semantic_op_index] if semantic_op_index < len(captured_attempts) else 1
                    is_fallback = False
                    semantic_op_index += 1  # Only increment when we consume a captured code
                else:
                    # Out of bounds: use mock code
                    code = _mock_generated_code_for_node(display_id, node.label, node.type)
                    node_cost = 0.0
                    node_retries = 1
                    is_fallback = True

                # CRITICAL: Use consistent ID system with terminal/input_summary events
                emit_node_id = compile_to_skrub.get(node.id, node.id) if (use_skrub_ids and compile_to_skrub) else node.id
                payload = {
                    "type": "node_code",
                    "node_id": emit_node_id,
                    "generated_code": code,
                    "retries": node_retries,
                    "cost_usd": node_cost,
                    "is_fallback": is_fallback,
                }
                yield _sse(payload)
                emitted_node_code_ids.add(emit_node_id)  # Track to prevent duplicate emissions
                time.sleep(0.05)

        # ═══════════════════════════════════════════════════════════════════════════════
        # ID Matching System — Why We Need to Map Node IDs
        # ═══════════════════════════════════════════════════════════════════════════════
        #
        # PROBLEM: Three ID systems that need to work together
        # ────────────────────────────────────────────────────────────────────────────────
        # 1. Static compile IDs (from parsing source code):
        #    - Semantic names like "var_products_4", "subsample_5", "sem_gen_features_6"
        #    - Fast to generate (no pipeline execution)
        #    - Assigned by document order (line numbers)
        #    - Used by 'runnable' nodes below
        #
        # 2. Dynamic compile IDs (from running pipeline to get skrub graph):
        #    - Numeric IDs like "0", "1", "2" (assigned by skrub at runtime)
        #    - Accurate graph structure (captures all operations: groupby -> agg -> reset_index)
        #    - Frontend receives these in compile response (always dynamic)
        #
        # 3. Runtime execution IDs (from this execute stream):
        #    - Numeric IDs like "0", "1", "2", "3" (assigned by skrub during execution)
        #    - MAY DIFFER from dynamic compile IDs because pipeline runs twice!
        #    - This is the source of truth for matching node_code events to graph nodes
        #
        # WHY THE PROBLEM EXISTS:
        # ────────────────────────────────────────────────────────────────────────────────
        # - Compile and execute both run the pipeline separately (dynamic extraction only)
        # - Skrub assigns numeric node IDs during each run
        # - Skrub assigns numeric node IDs during each run
        # - Different runs can produce different IDs (e.g., compile: {0,1,7}, execute: {0,1,2,3})
        # - Frontend displays compile graph but receives node_code events from execute
        # - IDs must match or frontend can't show code when user clicks a node!
        #
        # OUR SOLUTION:
        # ────────────────────────────────────────────────────────────────────────────────
        # 1. Execute emits skrub_graph event with the ACTUAL runtime graph used
        # 2. Frontend uses this runtime graph (not compile preview) for node ID lookups
        # 3. Build skrub_to_compile mapping for backward compatibility / debugging
        # 4. Emit node_code events with runtime skrub IDs (numeric)
        # 5. Frontend matches events to runtime graph nodes by ID
        #
        # KEY INSIGHT:
        # ────────────────────────────────────────────────────────────────────────────────
        # The runtime graph from execute is the single source of truth for node IDs.
        # Compile preview graph is for initial visualization only.
        # Once execution starts, frontend switches to using runtime graph for all ID matching.
        #
        # ═══════════════════════════════════════════════════════════════════════════════

        # Build skrub to compile mapping (used for skrubToCompileId in skrub_graph event)
        skrub_to_compile = _build_skrub_to_compile_id(graph_from_run, runnable) if graph_from_run and runnable else {}
        compile_to_skrub = {v: k for k, v in skrub_to_compile.items()}

        # Emit node_code for skrub semantic nodes so clicking them in the graph shows generated code.
        # When runner sent skrub_node_id with each block, use code_by_skrub; else fall back to label/occurrence.
        sempipes_node_ids = graph_from_run.get("sempipesNodeIds", []) if graph_from_run else []
        runner_nodes = (graph_from_run or {}).get("nodes") or []

        if code_by_skrub:
            for skid in sempipes_node_ids:
                if skid in code_by_skrub and skid not in emitted_node_code_ids:
                    info = code_by_skrub[skid]
                    # Emit skrub node ID directly (runtime ID from graph_from_run)
                    # This matches the graph node IDs in the skrub_graph event sent to frontend
                    payload = {
                        "type": "node_code",
                        "node_id": skid,
                        "generated_code": info["code"],
                        "retries": info["attempts"],
                        "cost_usd": info["cost_usd"],
                        "is_fallback": False,
                    }
                    yield _sse(payload)
                    emitted_node_code_ids.add(skid)  # Track to prevent duplicates
                    time.sleep(0.02)
        else:
            # Fallback: match by label and occurrence (document vs topo order may differ).
            # Only count semantic operators since captured_codes only contains semantic operator code.
            label_to_semantic_op_index: dict[str, list[int]] = {}
            semantic_op_idx = 0
            for node in runnable:
                if (node.type or "").lower() != "input":
                    if _is_semantic_operator(node.label):  # Only count semantic operators
                        label = (node.label or "").lower()
                        if label not in label_to_semantic_op_index:
                            label_to_semantic_op_index[label] = []
                        label_to_semantic_op_index[label].append(semantic_op_idx)
                        semantic_op_idx += 1
            label_usage: dict[str, int] = {}
            for skid in sempipes_node_ids:
                # Skip if already emitted in main loop
                if skid in emitted_node_code_ids:
                    continue
                skrub_node = next((sn for sn in runner_nodes if sn.get("id") == skid), None)
                if not skrub_node:
                    continue
                label = (skrub_node.get("label", "") or "").lower()
                occurrence = label_usage.get(label, 0)
                op_indices = label_to_semantic_op_index.get(label, [])
                if occurrence < len(op_indices):
                    code_idx = op_indices[occurrence]
                    label_usage[label] = occurrence + 1
                    if code_idx < len(captured_codes):
                        code_str = captured_codes[code_idx]
                        cost_usd = captured_costs[code_idx] if code_idx < len(captured_costs) else 0.0
                        retries = captured_attempts[code_idx] if code_idx < len(captured_attempts) else 1
                        # Emit skrub node ID directly (matches the graph node IDs from dynamic compilation)
                        payload = {
                            "type": "node_code",
                            "node_id": skid,
                            "generated_code": code_str,
                            "retries": retries,
                            "cost_usd": cost_usd,
                            "is_fallback": False,
                        }
                        yield _sse(payload)
                        emitted_node_code_ids.add(skid)  # Track to prevent duplicates
                        time.sleep(0.02)

        # Note: input_summary events for non-semantic nodes already emitted during main loop (lines 700-704)
        # Semantic nodes get node_code events above; non-semantic nodes only get input_summary (not node_code)

        # Emit graph when we have nodes (from runner ##SKRUB_GRAPH## or fallback from compile)
        if graph_from_run and len(runner_nodes) > 0:
            # skrub_to_compile already built earlier for node_code events
            yield _sse({'type': 'skrub_graph', 'graph': graph_from_run, 'skrubToCompileId': skrub_to_compile})
            # Note: input_summary events already emitted during node processing loop (lines 700-704)
            # No need to emit them again here

        # Emit node_data for each node preview (intermediate data from .skb.preview())
        compile_ids_with_node_data: set[str] = set()
        for preview in node_previews:
            # Preview node_id is "0", "1", etc. (skrub graph node id); emit with skrub_ prefix
            skid = preview.get("node_id", "")
            payload = {
                "type": "node_data",
                "node_id": f"skrub_{skid}",
                "schema": preview.get("schema", []),
                "sample": preview.get("sample", []),
                "row_count": preview.get("row_count", 0),
            }
            yield _sse(payload)
            # Also emit for the compile node id if we have a mapping
            if graph_from_run:
                skrub_to_compile = _build_skrub_to_compile_id(graph_from_run, runnable)
                compile_id = skrub_to_compile.get(skid)
                if compile_id:
                    compile_ids_with_node_data.add(compile_id)
                    payload_compile = {
                        "type": "node_data",
                        "node_id": compile_id,
                        "schema": preview.get("schema", []),
                        "sample": preview.get("sample", []),
                        "row_count": preview.get("row_count", 0),
                    }
                    yield _sse(payload_compile)

        # Emit node_data for VAR_PREVIEW (per-variable) for compile nodes not already covered
        if var_previews and runnable:
            var_producer = get_var_producer(input_code)
            try:
                static_nodes, _ = extract_nodes_with_ranges(input_code, prune=False)
                static_to_dynamic = _build_static_to_dynamic_id(static_nodes, runnable)
            except Exception:
                static_to_dynamic = {}
            for vp in var_previews:
                var_name = vp.get("var_name")
                if not var_name:
                    continue
                static_id = var_producer.get(var_name)
                compile_id = static_to_dynamic.get(static_id) if static_id else None
                if compile_id and compile_id not in compile_ids_with_node_data:
                    compile_ids_with_node_data.add(compile_id)
                    payload = {
                        "type": "node_data",
                        "node_id": compile_id,
                        "schema": vp.get("schema", []),
                        "sample": vp.get("sample", []),
                        "row_count": vp.get("row_count", 0),
                    }
                    yield _sse(payload)

        # Emit error if subprocess failed
        if exec_failed:
            yield _sse({'type': 'error', 'message': 'Pipeline execution failed. Check terminal for details.'})
            yield _sse({'type': 'terminal', 'line': 'Pipeline execution failed.'})
        else:
            yield _sse({'type': 'terminal', 'line': 'Done.'})
    except Exception as e:
        yield _sse({'type': 'error', 'message': str(e)})
    emit_ms = (time.perf_counter() - emit_start_time) * 1000 if emit_start_time else 0.0
    profile: dict = {}
    if prepare_ms > 0 or subprocess_wall_ms > 0 or emit_ms > 0:
        profile["prepare_ms"] = round(prepare_ms, 1)
        profile["subprocess_wall_ms"] = round(subprocess_wall_ms, 1)
        profile["emit_ms"] = round(emit_ms, 1)
    if runner_startup_ms is not None:
        profile["runner_startup_ms"] = round(runner_startup_ms, 1)
    if duration_ms is not None and duration_ms > 0:
        profile["runner_exec_ms"] = round(duration_ms, 1)
    if runner_post_exec_ms is not None:
        profile["runner_post_exec_ms"] = round(runner_post_exec_ms, 1)
    # Emit cost event so clients can show run cost before done (design: stream yields cost and done).
    yield _sse({'type': 'cost', 'total_usd': total_cost_usd})
    done_payload: dict = {"type": "done", "total_cost_usd": total_cost_usd, "duration_ms": duration_ms}
    if profile:
        done_payload["profile"] = profile
    yield _sse(done_payload)
