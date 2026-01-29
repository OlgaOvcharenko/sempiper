---
name: test-demo-backend
description: Runs, writes, and fixes pytest tests for the demo backend (FastAPI). Use when running, adding, or fixing backend tests; subagent freely fixes code and config so tests pass.
---

# Test Demo Backend (Subagent Skill)

**Delegate to the test-demo-backend subagent** when the user wants to run or add backend tests. The subagent runs in an isolated context with full backend-test instructions.

- **Subagent:** `.cursor/agents/test-demo-backend.md`
- **When to delegate:** Running backend tests, adding backend tests, or when test-demo-components (or run-all-demo-tests) delegates backend testing.

## Quick reference

If you run tests directly instead of delegating:

```bash
cd demo/backend
poetry run pytest tests/ -v
```

New tests: add under `demo/backend/tests/test_*.py`, use `TestClient(app)` from `main import app`. Do not edit files under `sempipes/`.

For full run/write details, use the **test-demo-backend** subagent.
