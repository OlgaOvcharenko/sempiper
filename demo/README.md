# SemPiper Web Demo

Interactive web UI for writing, compiling, and running [SemPipes](https://github.com/deem-data/sempipes/tree/main) pipelines. Edit declarative Python in a code editor, see the compiled data-flow graph, and inspect per-node results (generated code, data summaries, LLM cost).

The app has two modes:

- **Pipeline** — three-panel editor: pipeline code (left), interactive DAG (center), node details (right).
- **Optimizer** — browse optimization trajectories for semantic operator search.

## Pipeline mode

1. **Edit** — Write SemPipes pipeline code (`as_X`, `as_y`, `sem_fillna`, `sem_gen_features`, `skb.apply`, etc.). Example scripts load from `pipeline_scripts/` at the repo root.
2. **Compile** — Parses the code and builds a data-flow DAG with source ranges that link code positions to graph nodes.
3. **Run** — Executes the pipeline once via a subprocess. The backend streams per-node updates (generated code, previews, LLM cost) over SSE; the right panel updates live for the selected node.

Pipeline code in the editor is **real, runnable Python**. You can copy a script and run it outside the demo (notebook or `poetry run python script.py`) with the same dependencies (`skrub`, `sempipes`, `sklearn`). Example scripts use skrub datasets (e.g. `fetch_credit_fraud()` for fraud pipelines).

**LLM calls:** Running a pipeline with semantic operators requires API keys (e.g. `OPENAI_API_KEY` or `GEMINI_*` in a `.env` file at the repo root). Without SemPipes or keys, compile still works; execution of semantic operators will fail.

## Example scripts

Scripts live in `pipeline_scripts/` and are listed in `pipeline_scripts/manifest.json`:

| ID | Label |
|----|-------|
| `simple` | Fraud (simple) |
| `medium` | Fraud (medium) |
| `fraud` | Fraud detection |
| `house` | House prices |
| `museum` | Museum artworks |
| `new` | New |

Optimizer examples live in `optimizer_scripts/`.

## Project layout

```
demo/
├── backend/          # FastAPI app (main:app)
│   ├── routers/      # /api/compile, /api/execute, /api/optimizer/...
│   ├── services/     # compile, execute stream, cache, graph
│   └── tests/
├── frontend/         # React + Vite UI
│   ├── src/
│   └── tests/
└── docker-compose.yml
```

## Prerequisites

From the **repository root**:

1. **SemPipes** — Create a symlink: `ln -s /path/to/sempipes sempipes` (see root `README.md`).
2. **Python** — `poetry install`
3. **Node** — `cd demo/frontend && npm install`
4. **API keys** (for Run with semantic operators) — `.env` at repo root with your LLM provider keys.

## Run

**Quick start** (from repo root):

```bash
make run      # starts backend (:8000) and frontend (:5173)
```

Open **http://localhost:5173**. Stop with `make stop`.

**Manual start:**

```bash
# Terminal 1 — backend
cd demo/backend
poetry run uvicorn main:app --reload

# Terminal 2 — frontend
cd demo/frontend
npm run dev
```

The frontend proxies `/api` to the backend.

**Docker** (from repo root):

```bash
docker compose -f demo/docker-compose.yml up --build
```

## Tests

| Command | Where | Description |
|---------|-------|-------------|
| `poetry run pytest tests/ -v` | `demo/backend` | Backend tests |
| `npm test` | `demo/frontend` | Frontend tests (Vitest) |
| `make test` | repo root | Backend + frontend + E2E |

## API

Base path: `/api`. Interactive docs: **http://localhost:8000/docs**.

### Pipeline

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/scripts` | List example scripts (`?mode=normal` or `optimizer`) |
| `GET` | `/scripts/{id}` | Script source by id |
| `POST` | `/compile` | Compile pipeline → graph nodes, edges, source ranges |
| `POST` | `/execute` | Run pipeline → SSE stream of node events |
| `POST` | `/update-config` | Set LLM model and temperature |
| `GET` | `/sempipes-info` | Whether sempipes is available and current config |
| `DELETE` | `/cache` | Clear cache for a script + model + temperature |

**Compile** request body:

```json
{
  "input_code": "import skrub\n...",
  "script_id": "simple",
  "llm_name": "gpt-4o-mini",
  "temperature": 0.0,
  "use_cache": true
}
```

**Execute** streams Server-Sent Events. Event types include `node_code` (generated code per node), `node_data` (previews/summaries), and `done` (total LLM cost and duration).

### Optimizer

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/optimizer/options` | Available optimizer scripts and trajectories |
| `GET` | `/optimizer/by-script` | Trajectory for a script id |
| `GET` | `/optimizer/latest` | Most recent trajectory |
| `GET` | `/optimizer/final-code` | Final optimized code for a run |

## Logging

Each `make run` writes logs under `logs/` at the repo root:

- `logs/backend-*.log` — HTTP and lifecycle (concise)
- `logs/frontend-*.log` — Vite dev server
- `logs/runners/runner-*-<PID>.log` — full subprocess output per pipeline run (use this to debug failed runs)

## Tech stack

- **Backend:** FastAPI, Pydantic, Python 3.11+
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS
- **Editor:** Monaco (`@monaco-editor/react`)
- **Tests:** pytest (backend), Vitest + React Testing Library (frontend), Playwright (E2E)
