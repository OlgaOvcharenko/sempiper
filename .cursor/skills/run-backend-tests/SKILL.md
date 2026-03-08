---
name: run-backend-tests
description: Runs the demo backend test suite (pytest). Use when the user asks to run backend tests, test the backend, or verify backend/API code; or after editing demo/backend files.
---

# Run Backend Tests

## When to use

- User asks to run backend tests, test the backend, or run pytest for the demo.
- After editing files under `demo/backend/` to verify nothing is broken.

## How to run

From the **repository root**:

```bash
make test-backend
```

Or from the backend directory:

```bash
cd demo/backend && poetry run pytest tests/ -v
```

Uses Poetry and the root `pyproject.toml`; run from repo root after `poetry install` if needed.

## Notes

- Backend tests must not call real LLMs (see demo-tests-no-real-llms rule).
- If tests fail, fix or skip the failing test before considering the change done (see project rule run-tests-after-edits).
