---
name: run-all-demo-tests
description: Runs all demo test skills (backend + frontend + e2e) in parallel and fixes failures. Use when the user asks to run all tests, test the demo, or fix failing tests; subagent freely fixes code and config so all suites pass.
---

# Run All Demo Tests

This skill runs **all** demo test skills: backend (pytest), frontend (Vitest), and e2e (Playwright). Use it when the user wants to run every test or verify the full demo.

## Parts (what gets run)

1. **Backend** — `poetry run pytest tests/ -v` from `demo/backend`: health, scripts API, compile (graph + source ranges), execute stream (terminal, node_code, cost, input_summary).
2. **Graph JSON validation** — backend test `test_validate_graph_json_for_testing_only` (validates `validate_graph_json`; used internally by compile; no public validate endpoint).
3. **Frontend** — `npm test` from `demo/frontend`: Vitest + React Testing Library.
4. **E2E** — `npm run test:e2e` from `demo/frontend`: Playwright full-stack tests (starts backend + frontend via webServer; page load, Run button, graph, node details, script buttons).

## When to use

- User says "run all tests", "test the demo", "run every test", "full test suite", or similar.
- After edits that touch both backend and frontend (or when scope is unclear).
- When the user asks to "run the test skills" or "run all the test skills".

## How to run

**Preferred: delegate to the test-demo-components subagent** (`.cursor/agents/test-demo-components.md`). That subagent runs backend, frontend, and e2e tests, reports all outcomes, and **freely fixes** code or config when tests fail so all suites pass.

**Makefile (sequential):** From repo root: `make test` — runs backend, frontend, then e2e in order.

**Direct execution (parallel):** Run all three suites **in parallel** (e2e starts its own backend+frontend via Playwright webServer; no port conflict with unit tests):

- Terminal 1: `cd demo/backend && poetry run pytest tests/ -v`
- Terminal 2: `cd demo/frontend && npm test`
- Terminal 3: `cd demo/frontend && npm run test:e2e`

Or in one shell (all in parallel): `(cd demo/backend && poetry run pytest tests/ -v) & (cd demo/frontend && npm test) & (cd demo/frontend && npm run test:e2e) & wait` — then report all outcomes.

## Related subagents / skills

| Scope | Subagent | Skill |
|-------|----------|--------|
| Backend only | `test-demo-backend` | `test-demo-backend` |
| Frontend only | `test-demo-frontend` | `test-demo-frontend` |
| Both (all tests) | `test-demo-components` | `run-all-demo-tests` (this skill) |

## Checklist

- [ ] Delegate to **test-demo-components** subagent, or run backend, frontend, and e2e test commands.
- [ ] Report backend, frontend, and e2e results.
- [ ] Backend run includes graph validation test (`test_validate_graph_json_for_testing_only`).
