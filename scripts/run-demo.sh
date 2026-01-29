#!/usr/bin/env bash
# Start the demo: backend (uvicorn) and frontend (Vite). PIDs are saved so
# you can stop them with scripts/stop-demo.sh or: make stop-demo

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PIDS_FILE="$REPO_ROOT/.demo.pids"

cd "$REPO_ROOT"

if [ -f "$PIDS_FILE" ]; then
  echo "Demo may already be running (.demo.pids exists). Run 'make stop-demo' or 'scripts/stop-demo.sh' first."
  exit 1
fi

# Ensure frontend deps are installed
if [ ! -d "demo/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd demo/frontend && npm install)
fi

echo "Starting backend (http://localhost:8000)..."
poetry run uvicorn main:app --reload --app-dir demo/backend &
BACKEND_PID=$!

echo "Starting frontend (http://localhost:5173)..."
(cd demo/frontend && npm run dev) &
FRONTEND_PID=$!

echo "$BACKEND_PID" >> "$PIDS_FILE"
echo "$FRONTEND_PID" >> "$PIDS_FILE"
echo "Demo started. Backend PID $BACKEND_PID, frontend PID $FRONTEND_PID"
echo "Open http://localhost:5173 — stop with: make stop-demo"
