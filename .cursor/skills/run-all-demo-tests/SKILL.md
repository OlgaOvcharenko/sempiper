---
name: run-all-demo-tests
description: Runs all demo test skills (backend + frontend) and fixes failures. Use when the user asks to run all tests, test the demo, or fix failing tests; subagent freely fixes code and config so both suites pass.
---

# Run All Demo Tests

This skill runs **all** demo test skills: backend (pytest) and frontend (Vitest). Use it when the user wants to run every test or verify the full demo.

## When to use

- User says "run all tests", "test the demo", "run every test", "full test suite", or similar.
- After edits that touch both backend and frontend (or when scope is unclear).
- When the user asks to "run the test skills" or "run all the test skills".

## How to run

**Preferred: delegate to the test-demo-components subagent** (`.cursor/agents/test-demo-components.md`). That subagent runs backend and frontend tests in parallel, reports both outcomes, and **freely fixes** code or config when tests fail so both suites pass.

**Direct execution:** Run both suites in parallel:

- Terminal 1: `cd demo/backend && poetry run pytest tests/ -v`
- Terminal 2: `cd demo/frontend && npm test`

Or in one shell: `(cd demo/backend && poetry run pytest tests/ -v) & (cd demo/frontend && npm test) & wait` — then report both outcomes.

## Related subagents / skills

| Scope | Subagent | Skill |
|-------|----------|--------|
| Backend only | `test-demo-backend` | `test-demo-backend` |
| Frontend only | `test-demo-frontend` | `test-demo-frontend` |
| Both (all tests) | `test-demo-components` | `run-all-demo-tests` (this skill) |

## Checklist

- [ ] Delegate to **test-demo-components** subagent, or run backend and frontend test commands in parallel.
- [ ] Report both backend and frontend results.
