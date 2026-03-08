---
name: run-all-tests
description: Runs the full demo test suite (backend pytest, frontend Vitest, and E2E Playwright). Use when the user asks to run all tests, run the full test suite, or verify the whole demo; or before pushing or after broad changes.
---

# Run All Tests

## When to use

- User asks to run all tests, run the full test suite, or test the whole demo.
- Before pushing or after changes that touch both backend and frontend.
- To confirm nothing is broken across the stack.

## How to run

From the **repository root**:

```bash
make test
```

This runs in order:

1. **Backend** — `cd demo/backend && poetry run pytest tests/ -v`
2. **Frontend** — `cd demo/frontend && npm test` (Vitest)
3. **E2E** — `cd demo/frontend && npm run test:e2e` (Playwright; starts backend and frontend via webServer)

## Notes

- E2E can be slower; it launches the app and runs browser tests.
- For quick verification after small edits, prefer `make test-backend` or `make test-frontend` (see run-backend-tests and run-frontend-tests skills).
