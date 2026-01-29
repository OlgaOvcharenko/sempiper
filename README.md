# sempipes-demo

Repository for the sempipes demo (VLDB-style web demo: DSL/SQL input → generated code). Dependencies are managed with **Poetry**; there is no `requirements.txt` — use **`pyproject.toml`** only. Sempipes is loaded as a local path dependency.

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

**Backend** (FastAPI, port 8000):

```bash
cd demo/backend
uvicorn main:app --reload
```

Use the Poetry environment (e.g. `poetry shell` from repo root first, or run `poetry run uvicorn main:app --reload` with `--app-dir demo/backend` from repo root).

**Frontend** (React + Vite, port 5173):

```bash
cd demo/frontend
npm install
npm run dev
```

The frontend proxies `/api` to the backend. Open **http://localhost:5173** once both are running.

**Tests**

- Backend: from repo root or `demo/backend` run `pytest` (after `poetry install` at root).
- Frontend: from `demo/frontend` run `npm test`.

**Docker (optional)**

From the **repository root**:

```bash
docker compose -f demo/docker-compose.yml up --build
```

Backend: :8000, frontend: :5173. The backend image is built from the root `pyproject.toml`.

---

More detail (API, tech stack, replacing the mock engine): see **`demo/README.md`**.
