"""
Pipeline execution: yield SSE events (terminal output and per-node generated code).
Uses sempipes for code generation when available; otherwise falls back to mock.
"""
import json
import time

from services.compile_parse import extract_nodes_with_ranges


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


def _generated_code_for_node(node_id: str, label: str, node_type: str) -> str:
    """Return generated code: use sempipes when available, else mock."""
    if node_type == "input":
        return _mock_generated_code_for_node(node_id, label, node_type)
    code = _generate_code_via_sempipes(label, node_type)
    return code if code else _mock_generated_code_for_node(node_id, label, node_type)


def stream_execute_events(input_code: str):
    """
    Yield SSE-formatted events: terminal (stdout line) and node_code (node_id, generated_code).
    Uses sempipes for operator code generation when available.
    """
    nodes, _ = extract_nodes_with_ranges(input_code)
    runnable = [n for n in nodes if n.type in ("input", "operator")]

    yield f"data: {json.dumps({'type': 'terminal', 'line': 'Starting pipeline execution...'})}\n\n".encode()
    time.sleep(0.3)

    for node in runnable:
        yield f"data: {json.dumps({'type': 'terminal', 'line': f'Running {node.label} ({node.id})...'})}\n\n".encode()
        time.sleep(0.4)
        code = _generated_code_for_node(node.id, node.label, node.type)
        yield f"data: {json.dumps({'type': 'node_code', 'node_id': node.id, 'generated_code': code})}\n\n".encode()
        time.sleep(0.2)

    yield f"data: {json.dumps({'type': 'terminal', 'line': 'Done.'})}\n\n".encode()
    yield f"data: {json.dumps({'type': 'done'})}\n\n".encode()
