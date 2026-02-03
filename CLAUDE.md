# Claude Project Rules

This file references the project rules located in `.cursor/rules/`. These rules apply when working with Claude on the sempipes_demo project.

## Always Apply Rules

The following rules must always be followed:

### 1. No Edits in sempipes/

See: `.cursor/rules/no-edit-sempipes.mdc`

The `sempipes/` folder is a **symbolic link** to an external repository. It is **read-only**.

- **Do not** create, edit, modify, or delete any files under `sempipes/`
- **Do not** suggest changes that would alter code, config, or assets inside `sempipes/`
- You may **read** files under `sempipes/` for reference or context only

If changes are needed in the sempipes codebase, direct the user to work in the actual sempipes repository.

### 2. Commit Conventions

See: `.cursor/rules/commit-conventions.mdc`

- Make **small, frequent commits** (one logical change per commit)
- Use **one-line commit messages**; keep them short and clear
- Prefer concrete messages (e.g. "Add README for Cursor rules") over vague ones (e.g. "Update stuff")

### 3. Setup and Run

See: `.cursor/rules/setup-and-run.mdc`

**Dependencies:**
- **Python**: Managed with **Poetry** only. Use `pyproject.toml` at the repository root (no `requirements.txt`)
- **Sempipes**: Provided via symbolic link `sempipes/`
- **Frontend**: Node/npm in `demo/frontend`

**Running the demo:**
1. **Install once** (from repo root): `poetry install`
2. **Start**: `make run` (starts backend and frontend; open http://localhost:5173)
3. **Stop**: `make stop`
4. **Or manually**:
   - Backend: `cd demo/backend` then `uvicorn main:app --reload` (on :8000)
   - Frontend: `cd demo/frontend`, `npm install`, then `npm run dev` (on :5173, proxies `/api` to backend)

**Tests:**
- **Backend**: Run `pytest` from repo root or `demo/backend`
- **Frontend**: From `demo/frontend`, run `npm test`

**Docker:**
From repo root: `docker compose -f demo/docker-compose.yml up --build`

### 4. Run Tests After Edits

See: `.cursor/rules/run-tests-after-edits.mdc`

After editing any demo code (backend, frontend, or shared behavior), **run the relevant tests** to verify behavior.

- **Backend edits**: Run backend tests
- **Frontend edits**: Run frontend tests
- **Both or API contract**: Run both suites (in parallel when possible)

**Very fast tests only** (ideally under 10 seconds total):
- **Backend**: From `demo/backend`, run `poetry run pytest tests/ -v`
- **Frontend**: From `demo/frontend`, run `npm test`

Keep tests fast; if a test is slow, fix or skip it for the default run.

### 5. Demo Tests: No Real LLM Calls

See: `.cursor/rules/demo-tests-no-real-llms.mdc`

Backend tests should stay **close to using sempipes** but **must not call real LLMs**. Tests must run fast without API keys or network.

**How to enforce:**
- **conftest.py** patches `litellm.completion` and `litellm.batch_completion`
- Tests using sempipes code generation explicitly patch `sempipes.llm.llm._generate_code_from_messages`

**Adding new tests that touch sempipes:**
1. Use `unittest.mock.patch` or pytest monkeypatch to replace LLM calls with fixed responses
2. Patch at the right level: `sempipes.llm.llm._generate_code_from_messages` for code generation
3. Skip the test if sempipes is not importable, rather than failing or calling the real API

### 6. Demo Inspired by Sempipes Notebooks

See: `.cursor/rules/demo-inspired-by-sempipes-notebooks.mdc`

The **sempipes** repository contains **notebook demos** (e.g. `sempipes/demo.ipynb`) that run real pipelines.

- **Do not edit** anything under `sempipes/`
- Use notebooks as **inspiration** for the web demo in `demo/`:
  - **Pipeline vocabulary**: prefer notebook-style APIs (e.g. `as_X`, `as_y`, `sem_fillna`, `sem_gen_features`, `skb.apply`, `apply_with_sem_choose`, `sem_choose`)
  - **Graph semantics**: middle panel's compiled graph should reflect the same steps as notebook computation graphs
  - **Right panel**: node details mirror what notebooks show per step (data summary, generated code, LLM/prompt stats)

### 7. Demo: Three-Panel Design

See: `.cursor/rules/demo-three-panel-design.mdc`

The demo UI has **three panels** side by side.

**Design goals (graph):**
- **Full DAG**: Every pipeline step is a node; edges reflect data flow
- **All nodes interactive**: Every node is clickable (drives right panel) and highlightable (cursor in editor highlights corresponding node)

**Minimal design:**
- Keep UI **minimal**: only what's needed to edit pipeline, see graph, inspect node details
- Remove **superfluous elements** that don't directly support editing, compiling, running, or inspecting

**1. Left panel — Pipeline editor:**
- Write Python code as **declarative pipelines** using sempipes
- **Real, runnable code**: must work outside the page (copy-paste runnable)
- **Code–graph link**: sempipe elements visually highlighted; cursor/click highlights corresponding nodes in graph

**2. Middle panel — Interactive graph:**
- Visualise **scrub-compiled graph** as **DAG** (data flow)
- Graph is **full DAG**: edges from producer to consumer (data dependencies, not document order)
- **All nodes interactive**: clickable and highlightable
- **Node sizes must not scale**: fixed pixel dimensions (no container scaling)

**3. Right panel — Node details / results:**
- Show **contextual content** for selected node
- **Input nodes**: data summary (schema, sample, stats)
- **Operator nodes**: generated code, LLM prompt stats, cost per node (USD), metadata
- **Live updates during execution**: code blocks update dynamically as execution progresses

**Execute (Play):**
- **Play button** executes the pipeline (in addition to Compile)
- **No terminal**: no dedicated console/log panel; feedback via right panel and run-level cost near Run button
- **Live node code**: per-node outputs stream; right panel live-updates as execution progresses

**UI theme:**
- **Bright / light theme**: light backgrounds (white/slate-50/zinc-50), dark text, light borders

### 8. No Bypass of Sempipes Operators

See: `.cursor/rules/no-bypass-sempipes-operators.mdc`

The demo must use **sempipes API and operators** as the pipeline code does.

**Rule:**
- **Do not** call `sempipes.llm.llm.generate_python_code` or `generate_python_code_from_messages` directly from demo backend
- **Do not** bypass sempipes operators. Generated code must come from **running the pipeline** (operators run and call LLM internally)
- Use same vocabulary as tests and pipeline scripts

**Allowed:**
- Running pipeline script in subprocess (e.g. skrub_graph_runner) where sempipes operators execute
- Capturing operator-generated code from pipeline run
- Mocking/patching for **tests only** (production path must not call LLM directly)

**Tests:**
- `test_execute_stream_does_not_call_sempipes_llm_directly` verifies this rule

---

## Project Structure

- **`demo/`** — VLDB-style code-gen demo (FastAPI backend, React frontend)
- **`demo/backend/`** — FastAPI app; entrypoint is `main:app`
- **`demo/frontend/`** — React + Vite app
- **`pipeline_scripts/`** — Example pipelines (simple.py, medium.py, full.py)
- **`sempipes/`** — Symbolic link to external sempipes repository (read-only)

## Additional Context

For full details on any rule, refer to the corresponding `.mdc` file in `.cursor/rules/`.
