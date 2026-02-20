"""
Extract real data summaries by executing script subparts.

For input nodes and non-semantic operators, we execute the script up to that point
to get actual DataFrame statistics instead of mock data.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _extract_script_up_to_line(script: str, end_line: int) -> str:
    """Extract script lines 1 through end_line (inclusive)."""
    lines = script.split('\n')
    return '\n'.join(lines[:end_line])


def _make_cache_key(script_part: str, variable_name: str) -> str:
    """Create cache key from script content and variable name."""
    content = json.dumps({"script": script_part.strip(), "var": variable_name}, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _execute_and_extract_summary(script_part: str, variable_name: str) -> Optional[dict]:
    """
    Execute script part and extract data summary (schema, sample, row_count).

    Returns dict with schema, sample, row_count, or None if execution fails.
    """
    # Create runner script that executes the code and extracts DataFrame info
    runner_script = f'''
import sys
import json
import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")

try:
    # Execute user code
    exec_globals = {{'__name__': '__main__'}}
    exec("""
{script_part}
""", exec_globals)
    
    # Extract the variable
    var = exec_globals.get("{variable_name}")
    if var is None:
        print(json.dumps({{"error": "Variable not found"}}))
        sys.exit(1)

    # If it's a DataOp (skrub lazy evaluation), evaluate it to get actual DataFrame
    # DataOps need .skb.eval() to materialize the data
    if hasattr(var, 'skb') and hasattr(var.skb, 'eval'):
        df = var.skb.eval()
    else:
        df = var

    # Extract schema (column names and dtypes)
    import numpy as np
    import pandas as pd
    
    schema = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        schema.append({{"name": col, "dtype": dtype}})
    
    # Extract sample (first 5 rows, converted to dict)
    sample = df.head(5).to_dict('records')
    
    # Convert numpy types to JSON-serializable types
    def convert_value(v):
        if isinstance(v, (np.integer, np.floating)):
            return float(v) if isinstance(v, np.floating) else int(v)
        elif isinstance(v, np.bool_):
            return bool(v)
        elif pd.isna(v):
            return None
        return str(v)
    
    sample = [
        {{k: convert_value(v) for k, v in row.items()}}
        for row in sample
    ]
    
    # Extract row count
    row_count = len(df)
    
    # Output as JSON
    result = {{
        "schema": schema,
        "sample": sample,
        "row_count": row_count
    }}
    print(json.dumps(result))
    
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
    sys.exit(1)
'''
    
    try:
        # Run in subprocess with timeout
        proc = subprocess.Popen(
            [sys.executable, "-c", runner_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = proc.communicate(timeout=10)  # 10 second timeout

        if proc.returncode != 0:
            return None

        # Parse output
        result = json.loads(stdout.strip())
        if "error" in result:
            return None

        return result

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return None


def get_data_summary(
    script: str,
    variable_name: str,
    end_line: int,
    cache_dir: Optional[Path] = None
) -> dict:
    """
    Get data summary for a variable by executing script up to end_line.

    Args:
        script: Full pipeline script
        variable_name: Name of variable to extract (e.g., "products")
        end_line: Line number where variable is defined (1-indexed)
        cache_dir: Optional cache directory for storing results

    Returns:
        Dict with schema, sample, row_count. Falls back to mock if execution fails.
    """
    # Extract script subpart
    script_part = _extract_script_up_to_line(script, end_line)

    # Check cache
    cache_key = _make_cache_key(script_part, variable_name)
    cache_file = None
    if cache_dir:
        cache_dir = Path(cache_dir) / "data_summaries"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{cache_key}.json"

        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                    return cached.get("summary", _fallback_summary(variable_name))
            except (json.JSONDecodeError, IOError):
                pass

    # Execute and extract
    summary = _execute_and_extract_summary(script_part, variable_name)

    # If execution failed, use fallback
    if summary is None:
        summary = _fallback_summary(variable_name)

    # Cache result
    if cache_file:
        try:
            with open(cache_file, 'w') as f:
                json.dump({"summary": summary}, f)
        except IOError:
            pass

    return summary


def _fallback_summary(variable_name: str) -> dict:
    """Fallback mock summary when real execution fails."""
    return {
        "schema": [{"name": "ID", "dtype": "int64"}],
        "sample": [{"ID": i} for i in range(1, 6)],
        "row_count": 5000
    }
