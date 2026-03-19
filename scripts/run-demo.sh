#!/usr/bin/env bash
# Start the demo: backend (uvicorn) and frontend (Vite). PIDs are saved so
# you can stop them with scripts/stop-demo.sh or: make stop

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PIDS_FILE="$REPO_ROOT/.demo.pids"

cd "$REPO_ROOT"

if [ -f "$PIDS_FILE" ]; then
  echo "Demo may already be running (.demo.pids exists). Run 'make stop' or 'scripts/stop-demo.sh' first."
  exit 1
fi

# Set up per-run log files (timestamped so each `make run` gets its own files)
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOGS_DIR="$REPO_ROOT/logs"
mkdir -p "$LOGS_DIR"
BACKEND_LOG="$LOGS_DIR/backend-$TIMESTAMP.log"
FRONTEND_LOG="$LOGS_DIR/frontend-$TIMESTAMP.log"
echo "Logging to $LOGS_DIR/backend-$TIMESTAMP.log and frontend-$TIMESTAMP.log"

# Ensure backend (Poetry) deps are installed so compile/execute have duckdb, tabpfn, etc.
echo "Ensuring backend dependencies are installed..."
poetry install --no-interaction

# Ensure frontend deps are installed
if [ ! -d "demo/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd demo/frontend && npm install)
fi

echo "Starting backend (http://localhost:8000)..."
poetry run uvicorn main:app --reload --reload-exclude "tests/*" --app-dir demo/backend 2>&1 | tee "$BACKEND_LOG" &
BACKEND_PID=$!

echo "Starting frontend (http://localhost:5173)..."
(cd demo/frontend && npm run dev) 2>&1 | tee "$FRONTEND_LOG" &
FRONTEND_PID=$!

echo "$BACKEND_PID" >> "$PIDS_FILE"
echo "$FRONTEND_PID" >> "$PIDS_FILE"
echo "Demo started. Backend PID $BACKEND_PID, frontend PID $FRONTEND_PID"
echo ""
echo "  >>> Open in your browser: http://localhost:5173  <<<"
echo "  (Use 5173 for the UI; 8000 is the API only. Stop with: make stop)"
echo ""
