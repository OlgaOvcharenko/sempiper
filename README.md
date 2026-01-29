# sempipes-demo

Repository for the sempipes demo (VLDB-style web demo: declarative Python pipelines → compiled graph → generated code and insights). Dependencies are managed with **Poetry**; there is no `requirements.txt` — use **`pyproject.toml`** only. Sempipes is loaded as a local path dependency.

**Inspiration:** The web demo is inspired by the **sempipes notebook demos** (e.g. `sempipes/demo.ipynb`, `demo__sem_fillna.ipynb`), which run real pipelines with `as_X`/`as_y`, `sem_fillna`, `sem_gen_features`, `apply_with_sem_choose`, `sem_choose`, and show a computation graph and result on a subsample. The web UI mirrors that flow: pipeline code → compiled graph → node details.

## Demo design (high level)

The demo UI is a **three-panel layout**:

1. **Left — Pipeline editor**  
   Editor for writing Python code as declarative pipelines using sempipes. The code is the source of truth; changes drive compilation and graph updates.

2. **Middle — Interactive graph**  
   Visualisation of the **scrub-compiled graph** (pipeline DAG). Nodes are clickable; selecting a node drives the content shown in the right panel.

3. **Right — Node details / results**  
   Contextual content for the **selected graph node**:
   - **Input nodes**: data summary (schema, sample, stats).
   - **Sempipes / operator nodes**: generated code, LLM prompt statistics, or other node-specific metadata (e.g. timings, options).

The design is also documented in **`.cursor/rules/demo-three-panel-design.mdc`** for consistent implementation and AI-assisted development.

## Setup

### 1. Symbolic link to sempipes

This project expects a `sempipes/` folder that is a **symbolic link** to the external sempipes repository:

1. **Clone this repository** (sempipes-demo).
2. **Clone sempipes** into a separate folder (e.g. a sibling of this repo):
   ```bash
   cd /path/to/parent
   git clone <sempipes-repo-url> sempipes
   ```
3. **Create the symbolic link** from inside the sempipes-demo directory:
   ```bash
   cd /path/to/sempipes_demo
   ln -s ../sempipes sempipes
   ```
   If you cloned sempipes elsewhere, use that path (e.g. `ln -s /absolute/path/to/sempipes sempipes`).

Do not edit files under `sempipes/` from this project; make changes in the actual sempipes repository.

### 2. Install dependencies (Poetry only)

From the **repository root**:

```bash
poetry install
```

This installs all dependencies (including sempipes from the `sempipes/` path) from `pyproject.toml`. There is no `requirements.txt`; the single source of truth is `pyproject.toml`.

### 3. Run the demo

**One command** (from repo root; starts backend and frontend in the background):

```bash
make run-demo
```

Then open **http://localhost:5173**. To stop the demo:

```bash
make stop-demo
```

**Or run backend and frontend manually** in two terminals:

- **Backend** (FastAPI, port 8000): `cd demo/backend` then `uvicorn main:app --reload` (or from root: `poetry run uvicorn main:app --reload --app-dir demo/backend`). The backend calls sempipes when it is importable; if sempipes or its dependencies fail to load, the demo still runs with mock-only behaviour and reports `sempipes_available: false` in responses.
- **Frontend** (React + Vite, port 5173): `cd demo/frontend`, `npm install`, then `npm run dev`. The frontend proxies `/api` to the backend.

**Tests**

- Backend: from repo root or `demo/backend` run `pytest` (after `poetry install` at root).
- Frontend: from `demo/frontend` run `npm test`.

**Code style**

- **Python** (like sempipes): Ruff (lint + format) and mypy. From repo root after `poetry install`:  
  `poetry run ruff check demo/`  
  `poetry run ruff format --check demo/`  
  `poetry run mypy demo/backend`  
  Or install pre-commit and run on staged files:  
  `poetry run pre-commit install`  
  then `poetry run pre-commit run --all-files` to check everything.  
  Only `demo/` is checked; `sempipes/` is excluded (read-only symlink).
- **Frontend** (TypeScript/React): ESLint and Prettier. From `demo/frontend`:  
  `npm run lint`  
  `npm run lint:fix`  
  `npm run format`  
  `npm run format:check`

**Docker (optional)**

From the **repository root**:

```bash
docker compose -f demo/docker-compose.yml up --build
```

Backend: :8000, frontend: :5173. The backend image is built from the root `pyproject.toml`.

---

More detail (API, tech stack, replacing the mock engine): see **`demo/README.md`**.
