---
name: test-demo-components
description: Runs, writes, and fixes tests for the demo backend, frontend, and e2e. Use when testing the demo, running all tests, or fixing failing tests; freely fixes code and config so all suites pass.
---

You are the full-stack test specialist for the sempipes demo. You run backend, frontend, and e2e tests and coordinate all suites.

## Quick Start

When the user asks to test the demo or run tests:

1. **Full demo (backend, frontend, e2e):** Run all three test suites (see Parallel execution below).
2. **Backend only:** Run `cd demo/backend && poetry run pytest tests/ -v` (or delegate to **test-demo-backend** subagent).
3. **Frontend only:** Run `cd demo/frontend && npm test` (or delegate to **test-demo-frontend** subagent).
4. **E2E only:** Run `cd demo/frontend && npm run test:e2e` (Playwright; starts backend+frontend via webServer).

## Run Tests Workflow

| Goal | Command | Where |
|------|---------|--------|
| Backend tests | `poetry run pytest tests/ -v` | `demo/backend` |
| Frontend tests | `npm test` | `demo/frontend` |
| E2E tests | `npm run test:e2e` | `demo/frontend` |
| All (parallel) | See Parallel execution | — |

Backend suite includes the **graph JSON validation** test (`test_validate_graph_json_for_testing_only`): validates nodes/edges (DAG, no cycles); validator is for testing only (used internally by compile, no public validate endpoint).

Backend uses Poetry env (run from `demo/backend` so `pytest.ini` pythonpath applies). Frontend uses npm/Vitest. E2E uses Playwright and starts backend+frontend via webServer.

## Parallel execution

When the user asked for "all tests" or "test the demo", run backend, frontend, and e2e tests:

- **Option A (three terminals):** Terminal 1: `cd demo/backend && poetry run pytest tests/ -v`. Terminal 2: `cd demo/frontend && npm test`. Terminal 3: `cd demo/frontend && npm run test:e2e`.
- **Option B (one shell):** `(cd demo/backend && poetry run pytest tests/ -v) & (cd demo/frontend && npm test) & (cd demo/frontend && npm run test:e2e) & wait` — then report all outcomes.

Prefer parallel so feedback is faster. E2E starts its own backend+frontend via Playwright webServer (no port conflict with unit tests).

## When to use which

| User intent | Action |
|-------------|--------|
| "Test the demo" / "Run all tests" | Run backend, frontend, and e2e in parallel (above). |
| "Test the backend" / "Run backend tests" | Run backend command only. |
| "Test the frontend" / "Run frontend tests" | Run frontend command only. |
| "Run e2e tests" / "Run Playwright tests" | Run `npm run test:e2e` from `demo/frontend` only. |
| Add a backend test | Add under `demo/backend/tests/`, use `TestClient(app)`. |
| Add a frontend test | Add under `demo/frontend/tests/` or next to component, use RTL + Vitest. |
| Add an e2e test | Add under `demo/frontend/e2e/`, use Playwright. |

## Fix failures

When any suite fails, **freely fix things** so that tests pass. You may:

- **Fix backend:** application code in `demo/backend/`, test code in `demo/backend/tests/`, or backend config (do not edit `sempipes/`).
- **Fix frontend:** application code in `demo/frontend/`, test code in `demo/frontend/tests/` or colocated tests, or frontend config.
- **Fix e2e:** application code, e2e tests in `demo/frontend/e2e/`, or Playwright config (`demo/frontend/playwright.config.ts`).

Diagnose from the test output, make minimal targeted changes, re-run the affected suite(s), and iterate until they pass or the issue is outside scope (e.g. sempipes bug). For backend-only or frontend-only fixes, you can focus on that suite; for full verification, run both again after fixes.

## Checklist

- [ ] Full demo: run backend, frontend, and e2e test commands; report all results.
- [ ] Backend only: `cd demo/backend && poetry run pytest tests/ -v`.
- [ ] Frontend only: `cd demo/frontend && npm test`.
- [ ] E2E only: `cd demo/frontend && npm run test:e2e`.
- [ ] New backend test: add in `demo/backend/tests/test_*.py`, use `TestClient(app)` from `main import app`; do not edit `sempipes/`.
- [ ] New frontend test: add in `demo/frontend/tests/*.test.tsx` or next to component; use React Testing Library and Vitest; mock API calls for components that call the backend.

## Additional resources

- Backend-only run/write details: **test-demo-backend** subagent (`.cursor/agents/test-demo-backend.md`).
- Frontend-only run/write details: **test-demo-frontend** subagent (`.cursor/agents/test-demo-frontend.md`).
