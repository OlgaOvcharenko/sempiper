"""
Pipeline execution: yield SSE events (terminal output, per-node generated code, cost).
Uses sempipes for code generation when available; otherwise falls back to mock.
Cost is tracked via monkey-patching litellm completion/batch_completion (see cost_tracking.py).
"""
import json
import time

from services.compile_parse import extract_nodes_with_ranges
from services.cost_tracking import track_llm_cost


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
    """Return mock generated code when sempipes is not used."""
    if node_type == "input":
        return f"# Input: {label}\n# node_id = {node_id}\ndata = load_input()"
    return f"# Generated for {label} ({node_id})\ndef step():\n    # Simulated output\n    return processed_data"


def _generate_code_via_sempipes(label: str, node_type: str) -> str | None:
    """
    Use sempipes LLM to generate a short code snippet for this node.
    Returns None if sempipes is unavailable or generation fails (caller should use mock).
    """
    try:
        from sempipes.llm.llm import generate_python_code
    except ImportError:
        return None
    prompt = (
        f"Generate exactly 3-6 lines of Python code that could be produced by a semantic pipeline "
        f"step of type '{label}' ({node_type}). No explanation, only code. Use comments to describe steps."
    )
    try:
        return generate_python_code(prompt)
    except Exception:
        return None


_MAX_RETRIES_PER_NODE = 3


def _generated_code_for_node_with_retries(
    node_id: str, label: str, node_type: str
) -> tuple[str, int]:
    """
    Return (generated_code, retries). For operator nodes, try sempipes up to
    _MAX_RETRIES_PER_NODE times; retries = number of attempts after the first.
    """
    if node_type == "input":
        return _mock_generated_code_for_node(node_id, label, node_type), 0
    retries = 0
    for attempt in range(_MAX_RETRIES_PER_NODE):
        code = _generate_code_via_sempipes(label, node_type)
        if code:
            return code, retries
        retries += 1
    return _mock_generated_code_for_node(node_id, label, node_type), retries


def stream_execute_events(input_code: str):
    """
    Yield SSE-formatted events: terminal, node_code, cost (when LLM used), and done.
    Uses sempipes for operator code generation when available. Tracks LLM cost via
    cost_tracking.track_llm_cost (completion and batch_completion).
    """
    nodes, _ = extract_nodes_with_ranges(input_code)
    runnable = [n for n in nodes if n.type in ("input", "operator")]

    yield f"data: {json.dumps({'type': 'terminal', 'line': 'Starting pipeline execution...'})}\n\n".encode()
    time.sleep(0.3)

    with track_llm_cost() as cost_list:
        for node in runnable:
            yield f"data: {json.dumps({'type': 'terminal', 'line': f'Running {node.label} ({node.id})...'})}\n\n".encode()
            time.sleep(0.4)
            if node.type == "input":
                summary = _mock_input_summary(node.id, node.label)
                yield f"data: {json.dumps({'type': 'input_summary', **summary})}\n\n".encode()
                time.sleep(0.1)
            start_len = len(cost_list)
            code, retries = _generated_code_for_node_with_retries(node.id, node.label, node.type)
            node_cost_usd = sum(cost_list[start_len:]) if cost_list else 0.0
            payload = {
                "type": "node_code",
                "node_id": node.id,
                "generated_code": code,
                "retries": retries,
                "cost_usd": node_cost_usd,
            }
            yield f"data: {json.dumps(payload)}\n\n".encode()
            time.sleep(0.2)

        total_cost_usd = sum(cost_list) if cost_list else 0.0

    yield f"data: {json.dumps({'type': 'terminal', 'line': 'Done.'})}\n\n".encode()
    yield f"data: {json.dumps({'type': 'cost', 'total_usd': total_cost_usd})}\n\n".encode()
    yield f"data: {json.dumps({'type': 'done', 'total_cost_usd': total_cost_usd})}\n\n".encode()
