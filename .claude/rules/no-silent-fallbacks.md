# No Silent Fallbacks

**Always apply this rule**

When a backend operation cannot produce a correct result, fail explicitly — do not
silently substitute a wrong or placeholder result.

## Rule

- Do not substitute wrong data, wrong code, or placeholder values when the correct
  result cannot be computed. Fail explicitly instead.
- Index-based ordering as a fallback for node assignment is forbidden — it masks
  broken attribution and silently shows wrong data.

## Examples of forbidden patterns

- Using code block index to assign codes to nodes when the ID-based mapping fails.
- Returning hardcoded/mock data when real data extraction fails (see no-simulated-data.md).
- Catching an exception and substituting a default without surfacing the failure.
- Emitting placeholder/mock `node_code` events with fake generated code.

## Correct pattern

Fail fast and signal clearly:
- Runner: skip emitting a result block when the node cannot be attributed.
- `execute_stream.py`: when no code is found for a semantic node, log an error, set
  `exec_failed=True`, and **skip** emitting `node_code` — do not emit placeholder code.
- Never increment an "op index" counter as a substitute for a correct ID-based lookup.

## Implementation anchor

- `demo/backend/services/skrub_graph_runner.py`: codes are attributed via `ref_to_graph_idx`
  (object-identity `is` comparison). Non-semantic codes and unmatched codes are silently dropped
  (not emitted), so `execute_stream.py` never receives a wrong code.
- `demo/backend/services/execute_stream.py`: when `code_by_skrub` has no entry for a semantic
  node, fail the run — no placeholder, no `is_fallback` field, no mock code.
