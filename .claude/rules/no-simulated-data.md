# No Simulated / Placeholder Data

**Always apply this rule**

The demo must never show fake, placeholder, or simulated data to the user.

## Rule

- **Do not** return mock schema, sample rows, or row counts as a fallback when real data cannot
  be obtained. Examples of forbidden patterns:
  - `{"schema": [{"name": "ID", "dtype": "int64"}], "sample": [{"ID": 1}], "row_count": 5000}`
  - Any hardcoded schema with generic columns like `"ID"`, `"target"`, etc.
  - Any hardcoded `row_count` (e.g. `5000`) that does not reflect actual data.
- **Do not** write functions named `_fallback_summary`, `_mock_input_summary`, or similar that
  return fabricated data when real data extraction fails.
- **Do not** emit `input_summary` or `node_data` SSE events populated with fabricated data.

## Correct behavior when real data is unavailable

- **Return `None`** from data-extraction helpers when real data cannot be obtained.
- **Skip emitting** the SSE event entirely when data is `None`; do not emit a placeholder.
- **Leave the UI empty**: the frontend already shows a "Run the pipeline to see…" message
  when no data is available — that message is the correct empty state.

## When real data IS available

Real data is available when:
- A `skrub.var()` has a default value (e.g. `skrub.var("products", dataset.products)`) and
  the script up to that line can be executed successfully.
- The `skrub_graph_runner` subprocess captures DataFrame previews via `.skb.preview()` and
  emits them as `##NODE_PREVIEW##` or `##NODE_INPUT_SUMMARY##` blocks.

Real data is NOT available when:
- `skrub.var("products")` has no default value and no data was provided at runtime.
- Script execution fails before the variable is defined.

In those cases: emit nothing (no fake fallback).

## Files to watch

| File | Forbidden pattern |
|------|-------------------|
| `demo/backend/services/execute_stream.py` | `_mock_input_summary()` |
| `demo/backend/services/data_summary_extractor.py` | `_fallback_summary()` |
| `demo/backend/services/skrub_graph_runner.py` | Any hardcoded schema/sample inside runner |
