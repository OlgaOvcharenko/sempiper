# Run the full demo (backend + frontend in background). PIDs saved to .demo.pids.
run:
	@scripts/run-demo.sh

# Stop the demo processes started by run.
stop:
	@scripts/stop-demo.sh

# Run all tests: backend (pytest), frontend (Vitest), and E2E (Playwright).
# E2E starts backend+frontend via webServer; run from repo root.
test:
	@$(MAKE) test-backend test-frontend test-e2e

# Verify live backend returns correct compile edges (subsample->as_X, subsample->as_y).
# Run after 'make run' to ensure backend has latest code. Fails if edges missing → restart backend.
verify-compile:
	@./scripts/verify-compile-edges.sh

test-backend:
	cd demo/backend && poetry run pytest tests/ -v

test-frontend:
	cd demo/frontend && npm test

test-e2e:
	cd demo/frontend && npm run test:e2e
