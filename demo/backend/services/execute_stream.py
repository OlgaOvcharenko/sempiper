"""
Pipeline execution: yield SSE events (terminal output, per-node generated code, cost).
We run the user's pipeline in a subprocess (skrub_graph_runner). Operator-generated code
comes from that run (runner captures sempipes.llm.generate_python_code_from_messages);
we parse ##SEMPIPES_NODE_CODE## blocks from stdout. We do not call the LLM directly.
If we get skrub's computation graph (DataOp.skb.draw_graph) we emit skrub_graph.
Cost is tracked only when LLM is called in-process (subprocess LLM calls are not tracked).
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time

from services.compile_parse import extract_nodes_with_ranges

logger = logging.getLogger(__name__)

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
_EXECUTION_STATS_MARKER = "##EXECUTION_STATS##"


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
    # Use greedy (.*) so we capture the full JSON (single- or multi-line) up to \\n##END##
    pattern = re.compile(
        re.escape(_SKRUB_GRAPH_MARKER) + r"\s*\n(.*)\n" + re.escape(_SKRUB_GRAPH_END),
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


def _mock_input_summary(node_id: str, label: str) -> dict:
    """Return mock schema, sample rows, and row count for an input node (demo; no real data)."""
    if label == "as_y":
        return {
            "node_id": node_id,
            "schema": [{"name": "target", "dtype": "int64"}],
            "sample": [{"target": 0}, {"target": 1}, {"target": 0}, {"target": 1}, {"target": 0}],
            "row_count": 5000,
        }
    return {
        "node_id": node_id,
        "schema": [{"name": "ID", "dtype": "int64"}],
        "sample": [{"ID": 1}, {"ID": 2}, {"ID": 3}, {"ID": 4}, {"ID": 5}],
        "row_count": 5000,
    }


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
        is_sem = t == "operator"
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
        is_sem = t == "operator"
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
    Build mapping from skrub graph node id to compile node id.
    Used by frontend to highlight code when user clicks a graph node.

    IMPORTANT: Matches by label ONLY. The skrub graph node order (from _Graph().run())
    may differ from document order, so we cannot use numeric index mapping.
    Handles multiple nodes with the same label by matching Nth occurrence in skrub graph
    to Nth occurrence in compile nodes (sorted by source_range.start_line for document order).
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

    # Track which occurrence of each label we've used
    label_usage: dict[str, int] = {}

    # Match by label, handling duplicates by tracking occurrences
    for sn in nodes:
        skid = sn.get("id")
        if not skid:
            continue
        label = (sn.get("label", "") or "").lower()
        occurrence = label_usage.get(label, 0)
        compile_ids = label_to_compile_ids.get(label, [])

        if occurrence < len(compile_ids):
            result[skid] = compile_ids[occurrence]
            label_usage[label] = occurrence + 1

    return result


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


def _save_skrub_svg_to_disk(svg: str, script_id: str) -> None:
    """Save native skrub SVG to demo/graph_svgs/{script_id}.svg, replacing existing file."""
    if not script_id or not svg:
        return
    svg = _sanitize_svg_for_save(svg)
    if not svg.startswith("<svg") or "</svg>" not in svg:
        return
    # Sanitize script_id to avoid path traversal
    safe_id = "".join(c for c in script_id if c.isalnum() or c in "-_") or "custom"
    os.makedirs(_GRAPH_SVGS_DIR, exist_ok=True)
    path = os.path.join(_GRAPH_SVGS_DIR, f"{safe_id}.svg")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        logger.info(f"Saved skrub native graph SVG to {path}")
    except OSError as e:
        logger.warning(f"Could not save SVG to {path}: {e}")


def stream_execute_events(input_code: str, script_id: str | None = None):
    """
    Yield SSE-formatted events: terminal, node_code (from pipeline run), input_summary, skrub_graph, cost, done.
    Operator-generated code comes from running the pipeline in a subprocess; we parse
    ##SEMPIPES_NODE_CODE## blocks from stdout. We do not call the LLM directly.
    """
    total_cost_usd = 0.0
    duration_ms = 0.0
    exec_failed = False
    try:
        nodes, compile_edges = extract_nodes_with_ranges(input_code)
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
        e2e_mode = os.environ.get("DEMO_E2E") == "1"
        if e2e_mode:
            logger.info("E2E mode: skipping subprocess, using fallback graph and mock code")
            graph_from_run = _build_fallback_graph_from_compile(nodes, compile_edges)
        else:
            logger.info(f"Starting subprocess for {len(operator_nodes)} operators (no timeout)")
        subprocess_env = os.environ.copy()
        if not e2e_mode:
            # Prepare environment: pass sempipes config to subprocess
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
            try:
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
                    proc.wait()  # No timeout - let operators run as long as needed
                finally:
                    reader.join(timeout=1.0)
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
                # Extract skrub graph dict (##SKRUB_GRAPH##), native SVG (##SKRUB_GRAPH_SVG##), node previews (##NODE_PREVIEW##), and execution stats (##EXECUTION_STATS##)
                if decoded:
                    graph_from_run = _parse_skrub_graph_from_stdout(decoded)
                    svg_from_run = _parse_skrub_svg_from_stdout(decoded)
                    node_previews = _parse_node_previews_from_stdout(decoded)
                    exec_stats = _parse_execution_stats_from_stdout(decoded)
                    if exec_stats:
                        total_cost_usd = exec_stats.get("cost_usd", 0.0)
                        duration_ms = exec_stats.get("duration_ms", 0.0)
                        logger.info(f"Parsed execution stats: duration={duration_ms:.0f}ms, cost=${total_cost_usd:.6f}")
                    logger.info(f"Parsed {len(node_previews)} node previews from subprocess")
                    if not svg_from_run:
                        idx = decoded.find("<svg")
                        if idx >= 0:
                            svg_from_run = decoded[idx:].strip() or None
                    if not graph_from_run:
                        graph_from_run = _build_fallback_graph_from_compile(nodes, compile_edges)
                    # Save native skrub SVG to disk, keyed by script name
                    if svg_from_run and script_id:
                        _save_skrub_svg_to_disk(svg_from_run, script_id)
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

        yield f"data: {json.dumps({'type': 'terminal', 'line': 'Starting pipeline execution...'})}\n\n".encode()
        time.sleep(0.3)

        op_index = 0
        for node in runnable:
            yield f"data: {json.dumps({'type': 'terminal', 'line': f'Running {node.label} ({node.id})...'})}\n\n".encode()
            time.sleep(0.4)
            if node.type == "input":
                summary = _mock_input_summary(node.id, node.label)
                yield f"data: {json.dumps({'type': 'input_summary', **summary})}\n\n".encode()
                time.sleep(0.1)
                code = _mock_generated_code_for_node(node.id, node.label, node.type)
                is_fallback = True
                node_cost = 0.0
                node_retries = 0
            else:
                skid = compile_to_skrub.get(node.id) if compile_to_skrub else None
                if skid is not None and skid in code_by_skrub:
                    code = code_by_skrub[skid]["code"]
                    node_cost = code_by_skrub[skid]["cost_usd"]
                    node_retries = code_by_skrub[skid]["attempts"]
                    is_fallback = False
                else:
                    if op_index < len(captured_codes):
                        code = captured_codes[op_index]
                        node_cost = captured_costs[op_index] if op_index < len(captured_costs) else 0.0
                        node_retries = captured_attempts[op_index] if op_index < len(captured_attempts) else 1
                        is_fallback = False
                    else:
                        code = _mock_generated_code_for_node(node.id, node.label, node.type)
                        node_cost = 0.0
                        node_retries = 1
                        is_fallback = True
                    op_index += 1
            payload = {
                "type": "node_code",
                "node_id": node.id,
                "generated_code": code,
                "retries": node_retries,
                "cost_usd": node_cost,
                "is_fallback": is_fallback,
            }
            yield f"data: {json.dumps(payload)}\n\n".encode()
            time.sleep(0.2)

        # Emit node_code for skrub semantic nodes so clicking them in the graph shows generated code.
        # When runner sent skrub_node_id with each block, use code_by_skrub; else fall back to label/occurrence.
        sempipes_node_ids = graph_from_run.get("sempipesNodeIds", []) if graph_from_run else []
        runner_nodes = (graph_from_run or {}).get("nodes") or []

        if code_by_skrub:
            for skid in sempipes_node_ids:
                if skid in code_by_skrub:
                    info = code_by_skrub[skid]
                    payload = {
                        "type": "node_code",
                        "node_id": f"skrub_{skid}",
                        "generated_code": info["code"],
                        "retries": info["attempts"],
                        "cost_usd": info["cost_usd"],
                        "is_fallback": False,
                    }
                    yield f"data: {json.dumps(payload)}\n\n".encode()
                    time.sleep(0.1)
        else:
            # Fallback: match by label and occurrence (document vs topo order may differ).
            label_to_op_index: dict[str, list[int]] = {}
            op_idx = 0
            for node in runnable:
                if (node.type or "").lower() != "input":
                    label = (node.label or "").lower()
                    if label not in label_to_op_index:
                        label_to_op_index[label] = []
                    label_to_op_index[label].append(op_idx)
                    op_idx += 1
            label_usage: dict[str, int] = {}
            for skid in sempipes_node_ids:
                skrub_node = next((sn for sn in runner_nodes if sn.get("id") == skid), None)
                if not skrub_node:
                    continue
                label = (skrub_node.get("label", "") or "").lower()
                occurrence = label_usage.get(label, 0)
                op_indices = label_to_op_index.get(label, [])
                if occurrence < len(op_indices):
                    code_idx = op_indices[occurrence]
                    label_usage[label] = occurrence + 1
                    if code_idx < len(captured_codes):
                        code_str = captured_codes[code_idx]
                        cost_usd = captured_costs[code_idx] if code_idx < len(captured_costs) else 0.0
                        retries = captured_attempts[code_idx] if code_idx < len(captured_attempts) else 1
                        payload = {
                            "type": "node_code",
                            "node_id": f"skrub_{skid}",
                            "generated_code": code_str,
                            "retries": retries,
                            "cost_usd": cost_usd,
                            "is_fallback": False,
                        }
                        yield f"data: {json.dumps(payload)}\n\n".encode()
                        time.sleep(0.1)

        # Emit node_code for skrub input/non-semantic nodes so they get "done" status in the graph
        runner_nodes = (graph_from_run or {}).get("nodes") or []
        for sn in runner_nodes:
            skid = sn.get("id")
            if not skid or skid in sempipes_node_ids:
                continue
            label = sn.get("label", "")
            compile_node = next((n for n in runnable if (getattr(n, "label", n.id) or "") == label), None)
            if compile_node:
                node_type = (getattr(compile_node, "type", "") or "operator").lower()
                code = _mock_generated_code_for_node(
                    getattr(compile_node, "id", ""), label, node_type
                )
                payload = {
                    "type": "node_code",
                    "node_id": f"skrub_{skid}",
                    "generated_code": code,
                    "retries": 0,
                    "cost_usd": 0.0,
                    "is_fallback": True,
                }
                yield f"data: {json.dumps(payload)}\n\n".encode()
                time.sleep(0.05)

        # Emit graph when we have nodes (from runner ##SKRUB_GRAPH## or fallback from compile)
        if graph_from_run and len(runner_nodes) > 0:
            skrub_to_compile = _build_skrub_to_compile_id(graph_from_run, runnable)
            yield f"data: {json.dumps({'type': 'skrub_graph', 'graph': graph_from_run, 'skrubToCompileId': skrub_to_compile})}\n\n".encode()
            # Emit input_summary with skrub node ids so frontend can show data when user selects input nodes
            for sn in runner_nodes:
                skid = sn.get("id")
                if not skid or skid in sempipes_node_ids:
                    continue
                compile_node = next((n for n in runnable if (getattr(n, "label", n.id) or "") == sn.get("label", "")), None)
                if compile_node and (getattr(compile_node, "type", "") or "").lower() == "input":
                    summary = _mock_input_summary(f"skrub_{skid}", sn.get("label", ""))
                    yield f"data: {json.dumps({'type': 'input_summary', **summary})}\n\n".encode()

        # Emit node_data for each node preview (intermediate data from .skb.preview())
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
            yield f"data: {json.dumps(payload)}\n\n".encode()
            # Also emit for the compile node id if we have a mapping
            if graph_from_run:
                skrub_to_compile = _build_skrub_to_compile_id(graph_from_run, runnable)
                compile_id = skrub_to_compile.get(skid)
                if compile_id:
                    payload_compile = {
                        "type": "node_data",
                        "node_id": compile_id,
                        "schema": preview.get("schema", []),
                        "sample": preview.get("sample", []),
                        "row_count": preview.get("row_count", 0),
                    }
                    yield f"data: {json.dumps(payload_compile)}\n\n".encode()

        # Emit error if subprocess failed
        if exec_failed:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Pipeline execution failed. Check terminal for details.'})}\n\n".encode()
            yield f"data: {json.dumps({'type': 'terminal', 'line': 'Pipeline execution failed.'})}\n\n".encode()
        else:
            yield f"data: {json.dumps({'type': 'terminal', 'line': 'Done.'})}\n\n".encode()
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n".encode()
    yield f"data: {json.dumps({'type': 'cost', 'total_usd': total_cost_usd})}\n\n".encode()
    yield f"data: {json.dumps({'type': 'done', 'total_cost_usd': total_cost_usd, 'duration_ms': duration_ms})}\n\n".encode()
