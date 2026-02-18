"""Cache utility functions."""

import hashlib


def make_cache_key(script: str, temperature: float | None, llm_name: str | None) -> str:
    """
    Generate a deterministic cache key from pipeline parameters.

    Args:
        script: Pipeline source code
        temperature: LLM temperature parameter
        llm_name: LLM model name

    Returns:
        16-character hex hash string
    """
    # Create deterministic string from inputs
    temp_str = f"{temperature:.10f}" if temperature is not None else "none"
    model_str = llm_name or "none"
    combined = f"{script}|{temp_str}|{model_str}"

    # Generate hash
    hash_obj = hashlib.sha256(combined.encode("utf-8"))
    return hash_obj.hexdigest()[:16]
