# Run the full demo (backend + frontend in background). PIDs saved to .demo.pids.
run:
	@scripts/run-demo.sh

# Stop the demo processes started by run.
stop:
	@scripts/stop-demo.sh

# Run all tests: backend (pytest) and frontend (Vitest) in parallel, then E2E (Playwright).
# E2E starts backend+frontend via webServer; run from repo root.
test:
	@( $(MAKE) test-backend & B=$$!; $(MAKE) test-frontend & F=$$!; wait $$B; BX=$$?; wait $$F; FX=$$?; exit $$((BX|FX)) ) && $(MAKE) test-e2e

# Verify live backend returns correct compile edges (subsample->as_X, subsample->as_y).
# Run after 'make run' to ensure backend has latest code. Fails if edges missing → restart backend.
verify-compile:
	@./scripts/verify-compile-edges.sh

# -n auto: run pytest in parallel (one worker per CPU) for much faster backend tests.
test-backend:
	cd demo/backend && poetry run pytest tests/ -v -n auto

test-frontend:
	cd demo/frontend && npm test

test-e2e:
	cd demo/frontend && npm run test:e2e
