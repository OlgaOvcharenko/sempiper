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

# Marker and format emitted by skrub_graph_runner for each operator-generated code block.
_SEMPIPES_NODE_CODE_MARKER = "##SEMPIPES_NODE_CODE##"
_SEMPIPES_NODE_CODE_END = "##END##"


def _parse_captured_codes_from_stdout(stdout_str: str) -> list[str]:
    """
    Parse ##SEMPIPES_NODE_CODE##\\n{json}\\n##END## blocks from runner stdout.
    Returns list of code strings in index order (by "index" in each JSON).
    """
    codes_by_index: dict[int, str] = {}
    pattern = re.compile(
        re.escape(_SEMPIPES_NODE_CODE_MARKER) + r"\s*\n([^\n]+)\n" + re.escape(_SEMPIPES_NODE_CODE_END)
    )
    for m in pattern.finditer(stdout_str):
        try:
            obj = json.loads(m.group(1))
            idx = obj.get("index", len(codes_by_index))
            code = obj.get("code", "")
            codes_by_index[idx] = code if isinstance(code, str) else str(code)
        except (json.JSONDecodeError, TypeError):
            continue
    return [codes_by_index[i] for i in sorted(codes_by_index)]


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


def stream_execute_events(input_code: str):
    """
    Yield SSE-formatted events: terminal, node_code (from pipeline run), input_summary, skrub_graph, cost, done.
    Operator-generated code comes from running the pipeline in a subprocess; we parse
    ##SEMPIPES_NODE_CODE## blocks from stdout. We do not call the LLM directly.
    """
    total_cost_usd = 0.0
    try:
        nodes, _ = extract_nodes_with_ranges(input_code)
        runnable = [n for n in nodes if n.type in ("input", "operator")]
        operator_nodes = [n for n in runnable if n.type == "operator"]

        # Run pipeline subprocess first so we get captured operator code and optional SVG.
        captured_codes: list[str] = []
        svg_from_run: str | None = None
        _SKRUB_GRAPH_TIMEOUT = 120  # Allow time for LLM API calls
        logger.info(f"Starting subprocess with timeout {_SKRUB_GRAPH_TIMEOUT}s, {len(operator_nodes)} operators")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "services.skrub_graph_runner"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=_BACKEND_ROOT,
                env=os.environ.copy(),  # Pass environment variables (API keys) to subprocess
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
                proc.wait(timeout=_SKRUB_GRAPH_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            finally:
                reader.join(timeout=1.0)
            decoded = b"".join(stdout_chunks).decode("utf-8", errors="replace")
            captured_codes = _parse_captured_codes_from_stdout(decoded)
            logger.info(f"Subprocess returncode: {proc.returncode}, stdout: {len(decoded)} chars, captured: {len(captured_codes)} blocks")
            if len(decoded) > 0:
                logger.info(f"Stdout preview: {decoded[:200]}")
            if proc.returncode == 0 and decoded:
                idx = decoded.find("<svg")
                if idx >= 0:
                    svg_from_run = decoded[idx:].strip() or None
        except (FileNotFoundError, Exception) as e:
            logger.error(f"Subprocess exception: {type(e).__name__}: {e}")
            pass

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
            else:
                if op_index < len(captured_codes):
                    code = captured_codes[op_index]
                    is_fallback = False
                else:
                    code = _mock_generated_code_for_node(node.id, node.label, node.type)
                    is_fallback = True
                op_index += 1
            payload = {
                "type": "node_code",
                "node_id": node.id,
                "generated_code": code,
                "retries": 0,
                "cost_usd": 0.0,
                "is_fallback": is_fallback,
            }
            yield f"data: {json.dumps(payload)}\n\n".encode()
            time.sleep(0.2)

        if svg_from_run:
            yield f"data: {json.dumps({'type': 'skrub_graph', 'svg': svg_from_run})}\n\n".encode()

        yield f"data: {json.dumps({'type': 'terminal', 'line': 'Done.'})}\n\n".encode()
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n".encode()
    yield f"data: {json.dumps({'type': 'cost', 'total_usd': total_cost_usd})}\n\n".encode()
    yield f"data: {json.dumps({'type': 'done', 'total_cost_usd': total_cost_usd})}\n\n".encode()
