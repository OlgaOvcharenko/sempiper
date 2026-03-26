"""Cache utility functions."""

import hashlib
import re


def _normalize_script(script: str) -> str:
    """
    Normalize Python script for cache key generation.

    Normalization rules:
    - Strip trailing whitespace from each line
    - Remove blank lines (lines with only whitespace)
    - Remove comments (everything after #, but preserve # inside strings)
    - Preserve leading whitespace (indentation)

    Args:
        script: Raw Python script

    Returns:
        Normalized script string
    """
    lines = []
    for line in script.split("\n"):
        # Strip trailing whitespace
        line = line.rstrip()

        # Remove comments (simple approach: everything after #)
        # This doesn't handle # inside strings perfectly, but good enough for cache
        if "#" in line:
            # Find the first # not in a string literal
            in_string = False
            string_char = None
            for i, char in enumerate(line):
                if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                    if not in_string:
                        in_string = True
                        string_char = char
                    elif char == string_char:
                        in_string = False
                        string_char = None
                elif char == "#" and not in_string:
                    line = line[:i].rstrip()
                    break

        # Skip blank lines
        if line.strip():
            lines.append(line)

    return "\n".join(lines)


def make_cache_key(script: str, temperature: float | None, llm_name: str | None) -> str:
    """
    Generate a deterministic cache key from pipeline parameters.

    Applies normalization to ensure semantically equivalent inputs produce the same key:
    - Script: trailing whitespace stripped, blank lines and comments removed
    - Model name: case-insensitive, whitespace trimmed
    - Temperature: rounded to 2 decimal places

    Args:
        script: Pipeline source code
        temperature: LLM temperature parameter
        llm_name: LLM model name

    Returns:
        16-character hex hash string
    """
    # Normalize script
    normalized_script = _normalize_script(script)

    # Normalize temperature (round to 2 decimal places)
    if temperature is not None:
        temp_str = f"{round(temperature, 2):.2f}"
    else:
        temp_str = "none"

    # Normalize model name (lowercase, strip whitespace)
    if llm_name:
        model_str = llm_name.strip().lower()
    else:
        model_str = "none"

    # Create deterministic string from normalized inputs
    combined = f"{normalized_script}|{temp_str}|{model_str}"

    # Generate hash
    hash_obj = hashlib.sha256(combined.encode("utf-8"))
    return hash_obj.hexdigest()[:16]
