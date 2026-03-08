---
name: run-frontend-tests
description: Runs the demo frontend test suite (Vitest). Use when the user asks to run frontend tests, test the frontend, or verify frontend code; or after editing demo/frontend files.
---

# Run Frontend Tests

## When to use

- User asks to run frontend tests, test the frontend, or run Vitest.
- After editing files under `demo/frontend/` to verify nothing is broken.

## How to run

From the **repository root**:

```bash
make test-frontend
```

Or from the frontend directory:

```bash
cd demo/frontend && npm test
```

This runs Vitest once (`vitest run`). For watch mode use `npm run test:watch` from `demo/frontend`.

## Notes

- Tests are fast (unit/component tests only; no E2E).
- If tests fail, fix or skip the failing test before considering the change done (see project rule run-tests-after-edits).
