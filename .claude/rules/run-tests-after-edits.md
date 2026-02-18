# Run tests after edits

**Always apply this rule**

Run fast tests after editing demo elements to verify behavior; all verification runs must be very fast.

## When to run tests

After editing any demo code (backend, frontend, or shared behavior), **run the relevant tests** to verify behavior before considering the change done.

- **Backend edits** (`demo/backend/**`): Run backend tests.
- **Frontend edits** (`demo/frontend/**`): Run frontend tests.
- **Both or API contract**: Run both suites (in parallel when possible).

## Very fast tests only

**Any test run used for verification must be very fast** (ideally under 10 seconds total).

- **Backend**: From `demo/backend`, run `poetry run pytest tests/ -v`. Do not add slow fixtures, sleeps, or heavy integration in the default suite. Keep the test set small and fast.
- **Frontend**: From `demo/frontend`, run `npm test` (Vitest). Avoid long timeouts or E2E in the quick-verify run.
- **Full verify**: Run backend and frontend test commands in parallel so total wall-clock time stays low; do not run slow or optional suites unless the user explicitly asks.

If a test is slow, fix or skip it for the default run so that "run tests after edit" stays fast.
