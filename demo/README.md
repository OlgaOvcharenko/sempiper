# VLDB Code Gen Demo

Web demo for a VLDB paper: input DSL/SQL in a code editor, backend generates code (e.g. C++, Rust, LLVM IR), frontend shows result with syntax highlighting and metadata.

## Tech stack

- **Backend**: FastAPI + Pydantic + Python 3.11+
- **Frontend**: React 18 + TypeScript + Vite
- **Editor**: Monaco Editor (@monaco-editor/react)
- **Output highlighting**: Shiki
- **Data**: TanStack Query · **Styling**: Tailwind CSS
- **Tests**: pytest (backend), Vitest + React Testing Library (frontend)

## Setup

### Backend

Install dependencies from the **repository root** (single source of truth: `pyproject.toml`):

```bash
# From repo root
poetry install
cd demo/backend
uvicorn main:app --reload
```

Backend runs at **http://localhost:8000**.

### Frontend

```bash
cd demo/frontend
npm install
npm run dev
```

Frontend runs at **http://localhost:5173** and proxies `/api` to the backend.

### Docker (optional)

Backend image uses the root `pyproject.toml` (build context = repo root). From the **repository root**:

```bash
docker compose -f demo/docker-compose.yml up --build
```

Backend: :8000, frontend: :5173.

## Commands

| Command | Where | Description |
|--------|--------|-------------|
| `uvicorn main:app --reload` | `demo/backend` | Start backend on :8000 |
| `npm run dev` | `demo/frontend` | Start frontend on :5173 |
| `pytest` | repo root or `demo/backend` | Run backend tests (after `poetry install` at root) |
| `npm test` | `demo/frontend` | Run frontend tests |

## API

**POST /api/generate**

Request:

```json
{
  "input_code": "SELECT * FROM table...",
  "options": { "optimization_level": 2, "target": "cpp" }
}
```

Response:

```json
{
  "generated_code": "int main() { ... }",
  "language": "cpp",
  "compilation_time_ms": 12.5,
  "metadata": {
    "optimizations_applied": ["inlining", "vectorization"],
    "ir_size_bytes": 4096,
    "stages": [
      { "name": "parse", "time_ms": 1.2 },
      { "name": "optimize", "time_ms": 8.1 },
      { "name": "codegen", "time_ms": 3.2 }
    ]
  }
}
```

## Replacing the mock engine

The backend uses a mock in `backend/services/engine.py`. Replace the `CodeGenerator.generate()` implementation with your real system; keep the same return shape (dict with `generated_code`, `language`, `compilation_time_ms`, `metadata`).
