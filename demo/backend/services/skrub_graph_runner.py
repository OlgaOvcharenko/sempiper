"""
Run user pipeline code in an isolated namespace and output skrub's computation graph as SVG.
Used when the user clicks Run: we exec() the code, find any DataOp (object with .skb.draw_graph),
call draw_graph(), and print the SVG to stdout. The main process runs this with a timeout.

Also captures generated code from sempipes operators (when they call the LLM) so the demo
can show it without bypassing operators. Prints ##SEMPIPES_NODE_CODE##\\n{json}\\n##END## per capture.
"""
import json
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


def _find_dataop_and_draw(globals_dict):
    """Return SVG string from first object in globals_dict that has .skb.draw_graph()."""
    for _name, val in globals_dict.items():
        if _name.startswith("_"):
            continue
        try:
            skb = getattr(val, "skb", None)
            if skb is None:
                continue
            draw = getattr(skb, "draw_graph", None)
            if not callable(draw):
                continue
            graph = draw()
            if graph is None:
                continue
            svg = getattr(graph, "svg", None)
            if svg is not None:
                return svg.decode("utf-8") if isinstance(svg, bytes) else str(svg)
        except Exception:
            continue
    return None


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

    if exec_failed:
        sys.exit(1)

    svg = _find_dataop_and_draw(g)
    if svg:
        print(svg, end="")


if __name__ == "__main__":
    main()
