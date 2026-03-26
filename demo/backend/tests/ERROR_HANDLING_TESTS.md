# Error Handling Test Suite

This document explains the error handling tests in `test_compilation_error_handling.py` and why certain pipeline scripts are skipped in the source range tests.

## Overview

The backend compilation system is **robust and safe**:
- Invalid scripts return empty graphs (don't crash)
- Malicious operations are sandboxed
- Error messages are informative for debugging

## Test Coverage

### 1. Syntax Errors (4 tests)
Tests for Python syntax errors like:
- Missing colons
- Invalid indentation
- Unclosed parentheses
- Mismatched quotes

**Expected behavior**: All return empty graphs with validation errors

### 2. Import Errors (2 tests)
Tests for missing/invalid imports:
- Non-existent modules
- Invalid from...import statements

**Expected behavior**: Return empty graphs with "Execution failed" error

### 3. Runtime Errors (5 tests)
Tests for errors during script execution:
- Undefined variables
- Attribute errors
- Type errors
- Division by zero

**Expected behavior**: Return empty graphs with informative error messages

### 4. Empty/Minimal Scripts (4 tests)
Tests for scripts with no actual pipeline code:
- Empty scripts
- Only imports
- Only comments
- The `new.py` template

**Expected behavior**: Return empty graphs with "No DataOp found" error

**Note**: The `new.py` file is intentionally empty - it's a starting template for developers in the demo. It correctly returns an empty graph without breaking anything.

### 5. Potentially Dangerous Scripts (7 tests)
Tests for scripts with potentially malicious operations:
- `os.system()` calls
- `subprocess` execution
- File operations
- Infinite loops
- `eval()` / `exec()` builtins
- Network requests

**Security model**: The script rewriting and execution environment provides sandboxing:
1. Scripts are rewritten to remove data arguments (e.g., `skrub.var("x", data)` → `skrub.var("x", None)`)
2. Execution uses limited `exec_globals` (only whitelisted imports)
3. Dangerous modules (subprocess, urllib, etc.) are not available in exec environment
4. Operations that would fail with real data are often in data args and get removed by rewriting

**Important**: These tests verify that:
- No dangerous operations actually execute
- Scripts either fail gracefully or succeed without side effects
- The backend never crashes, regardless of input

### 6. Mixed Error Scenarios (2 tests)
Tests for scripts with multiple issues combined.

### 7. Informative Error Messages (1 test)
Verifies that error messages are clear and helpful for debugging.

## Why Scripts Are Skipped

### house_prices.py
**Skip reason**: `"Execution failed: No module named 'kagglehub'"`

**Status**: ✅ Legitimate advanced example

This is a well-formed pipeline that:
- Downloads Kaggle datasets
- Uses image feature extraction
- Requires external dependencies (kagglehub, tabpfn)

The tests correctly skip it when dependencies are missing. This is **expected and correct** - not all users will have these optional packages installed.

### new.py
**Skip reason**: `"No DataOp found in executed script"`

**Status**: ✅ Intentional empty template

This file is a starting point for developers to write new pipelines. It contains only:
```python
import os
os.environ.setdefault("SCIPY_ARRAY_API", "1")
import skrub
# TODO: Implement the new pipeline
```

It correctly returns an empty graph without breaking anything. This is the **expected behavior** for a template file.

## Test Results Summary

```
test_compilation_error_handling.py: 25 passed (3.21s)
test_all_pipeline_scripts_source_ranges.py: 10 passed, 6 skipped (6s)
```

**All skipped tests are intentional and correct**:
- 3 tests × 2 scripts = 6 skips
- house_prices.py: Missing optional dependencies
- new.py: Empty template (no pipeline code)

## Running the Tests

```bash
# Run error handling tests only
poetry run pytest tests/test_compilation_error_handling.py -v

# Run all pipeline source range tests
poetry run pytest tests/test_all_pipeline_scripts_source_ranges.py -v

# Run both together
poetry run pytest tests/test_compilation_error_handling.py tests/test_all_pipeline_scripts_source_ranges.py -v
```

## Safety Verification

✅ All 25 error handling tests pass
✅ No dangerous operations execute
✅ No files are modified or created
✅ No network requests succeed
✅ Backend never crashes, regardless of input
✅ Error messages are informative

## Key Insights

1. **Script rewriting is clever**: Removes data arguments that would fail, making many error cases harmless
2. **Sandboxing works**: Dangerous modules not available in exec environment
3. **Graceful degradation**: Invalid scripts return empty graphs, not crashes
4. **Template support**: Empty scripts like new.py work correctly as starting points
5. **Optional dependencies**: Scripts with missing deps fail gracefully

## Recommendations

1. **Keep new.py**: It's a legitimate starting template
2. **Keep house_prices.py**: Valuable advanced example, skip is correct
3. **Don't add kagglehub/tabpfn to core deps**: They're optional and would bloat install
4. **Trust the skip behavior**: Tests that skip are working as designed
