---
name: test-demo-frontend
description: Runs, writes, and fixes Vitest + React Testing Library tests for the demo frontend. Use when running, adding, or fixing frontend tests; subagent freely fixes code and config so tests pass.
---

# Test Demo Frontend (Subagent Skill)

**Delegate to the test-demo-frontend subagent** when the user wants to run or add frontend tests. The subagent runs in an isolated context with full frontend-test instructions.

- **Subagent:** `.cursor/agents/test-demo-frontend.md`
- **When to delegate:** Running frontend tests, adding frontend tests, or when test-demo-components (or run-all-demo-tests) delegates frontend testing.

## Quick reference

If you run tests directly instead of delegating:

```bash
cd demo/frontend
npm test
```

New tests: add under `demo/frontend/tests/*.test.tsx` or next to components; use React Testing Library and Vitest; mock API calls for components that call the backend.

For full run/write details, use the **test-demo-frontend** subagent.
