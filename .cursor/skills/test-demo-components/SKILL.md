---
name: test-demo-components
description: Runs, writes, and fixes tests for the demo backend and frontend. Use when testing the demo, running all tests, or fixing failing tests; subagent freely fixes code and config so both suites pass.
---

# Test Demo Components (Subagent Skill)

**Delegate to the test-demo-components subagent** when the user wants to test the demo, run all tests, or add backend or frontend tests. The subagent runs both suites (in parallel when appropriate) and knows when to run backend-only or frontend-only.

- **Subagent:** `.cursor/agents/test-demo-components.md`
- **When to delegate:** "Test the demo", "run all tests", add backend or frontend tests, or when the user asks to test components.

## Quick reference

If you run tests directly instead of delegating:

| Goal | Command | Where |
|------|---------|--------|
| Both (parallel) | Backend + frontend in two terminals or one shell with `& wait` | — |
| Backend only | `poetry run pytest tests/ -v` | `demo/backend` |
| Frontend only | `npm test` | `demo/frontend` |

For full workflow (parallel execution, when to use which, checklists), use the **test-demo-components** subagent. For running all test skills from one entry point, use the **run-all-demo-tests** skill.
