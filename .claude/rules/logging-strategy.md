# Logging Strategy

**Always apply this rule**

Two-tier logging: concise main log + per-run subprocess log files.

## Log files

| File | Contents |
|------|----------|
| `logs/backend-YYYYMMDD_HHMMSS.log` | Main backend log (uvicorn, HTTP, compile/execute lifecycle) |
| `logs/frontend-YYYYMMDD_HHMMSS.log` | Vite dev-server log |
| `logs/runners/runner-YYYYMMDD_HHMMSS-<PID>.log` | Full subprocess output per pipeline run |

Produced by `scripts/run-demo.sh` (`make run`). A new timestamped pair is created on each start.

## What goes where

### Main backend log (`logs/backend-*.log`)
- HTTP request lines (uvicorn access log)
- Compile/execute lifecycle: subprocess started (PID + log path), success/failure status, number of code blocks captured
- Warnings and errors from the FastAPI process itself
- **Not**: generated Python code, LiteLLM verbose output, pandas warnings — those belong in the runner log

### Runner log (`logs/runners/runner-*.log`)
Each pipeline subprocess (one per `/api/execute` call) gets its own log file capturing its full stdout+stderr, including:
- LiteLLM completion and success-handler messages
- The full generated Python code emitted by sempipes operators
- `##SEMPIPES_NODE_CODE##`, `##NODE_PREVIEW##`, `##NODE_INPUT_SUMMARY##` protocol blocks
- Pandas or other runtime warnings
- Python tracebacks if the pipeline fails

## How to debug

**Pipeline ran but produced wrong code or missing nodes:**
→ Open `logs/runners/runner-<PID>.log` for that run. Check LiteLLM output and `##SEMPIPES_NODE_CODE##` blocks.

**Pipeline subprocess failed (returncode != 0):**
→ The main log shows `FAILED (rc=N)`. Open the referenced runner log for the full traceback.

**Backend error unrelated to pipeline execution:**
→ Check `logs/backend-*.log` directly.

## Implementation (execute_stream.py)

- Subprocess stdout+stderr are merged (`stderr=subprocess.STDOUT`) and written line-by-line to the runner log file — **not** echoed to the backend's stdout.
- After the subprocess exits, the main logger emits one summary line:
  ```
  Subprocess PID {pid} OK — {n} code blocks captured, {chars} chars — log: {path}
  ```
  or `FAILED (rc={returncode})` if it exited non-zero.
- `_RUNNERS_LOG_DIR` constant points to `{repo_root}/logs/runners/`.

## What NOT to do

- **Do not** `print(chunk, file=sys.stdout)` subprocess output to the main backend stdout — this floods the backend log with LiteLLM noise and generated code.
- **Do not** add `logger.info(f"Stdout preview: ...")` lines — the runner log is the right place.
- **Do not** suppress the runner log; it is the primary debugging artifact for pipeline issues.
