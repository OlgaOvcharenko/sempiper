"""
Mock code generator. Uses sempipes when available (Poetry env); falls back to mock-only otherwise.
"""

import random
import time

try:
    from sempipes import get_config as _sempipes_get_config  # type: ignore[attr-defined]

    _sempipes_available = True
except ImportError:
    _sempipes_available = False
    _sempipes_get_config = None


def is_sempipes_available() -> bool:
    return _sempipes_available


# Simple global variable to persist config across requests (since sempipes uses ContextVar)
_PERSISTENT_CONFIG: dict | None = None


def get_sempipes_config() -> dict | None:
    """Return current sempipes config as a dict (persistent override or default), or None if unavailable."""
    # Priority: 1. Persistent override (set by frontend), 2. Default sempipes config
    if _PERSISTENT_CONFIG:
        return _PERSISTENT_CONFIG
    
    if not _sempipes_available or _sempipes_get_config is None:
        return None
    cfg = _sempipes_get_config()
    return cfg.to_dict() if hasattr(cfg, "to_dict") else None


def update_persistent_config(llm_name: str, temperature: float) -> dict:
    """Update the persistent configuration for subsequent requests."""
    global _PERSISTENT_CONFIG
    
    # Start with current config (or defaults from sempipes)
    base_config = get_sempipes_config() or {}
    
    # Construct updated config structure (matching sempipes.Config.to_dict format)
    # We maintain the structure manually since we want a simple dictionary for persistence
    new_config = base_config.copy()
    
    # Ensure llm_for_code_generation section exists
    if "llm_for_code_generation" not in new_config:
        new_config["llm_for_code_generation"] = {}
        
    new_config["llm_for_code_generation"] = {
        "name": llm_name,
        "parameters": {"temperature": temperature}
    }
    
    # Store globally
    _PERSISTENT_CONFIG = new_config
    
    # Also attempt to update the specialized sempipes ContextVar (for current request)
    if _sempipes_available:
        try:
            import sempipes
            sempipes.update_config(
                llm_for_code_generation=sempipes.LLM(
                    name=llm_name,
                    parameters={"temperature": temperature}
                )
            )
        except Exception:
            pass
            
    return new_config


class CodeGenerator:
    def generate(self, input_code: str, options: dict | None = None) -> dict:
        options = options or {}
        target = options.get("target", "cpp")
        # Simulate processing time
        time.sleep(random.uniform(0.01, 0.05))
        parse_ms = round(random.uniform(0.5, 2.0), 1)
        optimize_ms = round(random.uniform(5.0, 10.0), 1)
        codegen_ms = round(random.uniform(2.0, 5.0), 1)
        total_ms = round(parse_ms + optimize_ms + codegen_ms, 1)
        metadata = {
            "optimizations_applied": ["constant_folding", "dead_code_elimination"],
            "ir_size_bytes": 4096,
            "stages": [
                {"name": "parse", "time_ms": parse_ms},
                {"name": "optimize", "time_ms": optimize_ms},
                {"name": "codegen", "time_ms": codegen_ms},
            ],
        }
        if _sempipes_available and _sempipes_get_config is not None:
            try:
                cfg = _sempipes_get_config()
                metadata["sempipes_available"] = True
                metadata["sempipes_llm"] = getattr(getattr(cfg, "llm_for_code_generation", None), "name", None)
            except Exception:
                metadata["sempipes_available"] = False
        else:
            metadata["sempipes_available"] = False
        return {
            "generated_code": (
                "// Generated from input\n" f"int main() {{\n  // {len(input_code)} chars processed\n  return 0;\n}}"
            ),
            "language": target,
            "compilation_time_ms": total_ms,
            "metadata": metadata,
        }
