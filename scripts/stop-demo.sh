#!/usr/bin/env bash
# Stop the demo processes started by scripts/run-demo.sh (or make run).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PIDS_FILE="$REPO_ROOT/.demo.pids"

if [ ! -f "$PIDS_FILE" ]; then
  echo "No .demo.pids found; demo was not started via make run."
  exit 0
fi

while read -r pid; do
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "Stopped PID $pid"
  fi
done < "$PIDS_FILE"

rm -f "$PIDS_FILE"
echo "Demo stopped."
