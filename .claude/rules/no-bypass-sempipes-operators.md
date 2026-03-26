# No bypass of sempipes operators

**Always apply this rule**

Demo must use sempipes API and operators; do not bypass them or call LLM directly.

The demo must use **sempipes API and operators** as the pipeline code on the webpage does (e.g. `sempipes.as_X`, `sempipes.as_y`, `.sem_fillna`, `.sem_gen_features`).

## Rule

- **Do not** call `sempipes.llm.llm.generate_python_code` or `sempipes.llm.llm.generate_python_code_from_messages` directly from the demo backend.
- **Do not** bypass sempipes operators. Generated code for operator nodes must come from **running the pipeline** (so that sempipes operators run and call the LLM internally), not from a separate direct LLM call in the demo.
- Use the same vocabulary and flow as in the tests and pipeline scripts: pipeline code uses sempipes API and operators; the demo runs that pipeline and gets results (including generated code) from the operators.

## Allowed

- Running the user's pipeline script in a subprocess (e.g. skrub_graph_runner) where sempipes operators execute.
- Capturing operator-generated code from the pipeline run (e.g. by having the runner capture what operators produce when they run).
- Mocking or patching for **tests only** (so tests don't call real LLMs), while the **production code path** must not call the LLM directly.

## Tests

- `test_execute_stream_does_not_call_sempipes_llm_directly` (demo/backend/tests): patches `sempipes.llm.llm.generate_python_code` and `generate_python_code_from_messages` and asserts they are **not called** when POST /api/execute runs. Skips if sempipes.llm.llm is not importable.
