## Run executes exactly once

When the user clicks **Run** (`POST /api/execute`), the backend must execute the pipeline **exactly one time**.

- **Do not** trigger any second evaluation pass in order to “fill in” node previews / node details.
- **Do not** call `skrub._data_ops._evaluation.evaluate(...)` after the main run as a fallback. This can re-run the pipeline and can easily double runtime.
- Node previews / data needed for the UI must come from the **single** execution (captured during skrub’s evaluation inside the run).

### Failure policy

If the backend cannot extract the required node information from the single execution (e.g. preview capture is incomplete), then the run must **fail** and the UI must show a clear error. The correct user action is to retry, not for the backend to silently run the pipeline again.

### Implementation anchor

- Runner: `demo/backend/services/skrub_graph_runner.py`
  - `_get_skrub_dag_dict(...)` must not contain a fallback that evaluates the graph again.
- Streamer: `demo/backend/services/execute_stream.py`
  - A runner non-zero exit must be surfaced as an SSE `error` event (no retries).

