#!/usr/bin/env bash
# Stop the demo processes started by scripts/run-demo.sh (or make run).
# Also kills processes on ports 5173 (frontend) and 8000 (backend) that match
# our demo (Vite, uvicorn), since saved PIDs may be parent shells whose
# children survive. Only kills processes that match expected commands.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PIDS_FILE="$REPO_ROOT/.demo.pids"

# Return 0 if pid is our Vite dev server (node running vite)
is_our_vite() {
  local pid=$1
  [ -z "$pid" ] && return 1
  local args
  args=$(ps -p "$pid" -o args= 2>/dev/null) || return 1
  case "$args" in
    *[vV]ite*) return 0 ;;
    *node*[vV]ite*) return 0 ;;
    *) return 1 ;;
  esac
}

# Return 0 if pid is our uvicorn backend
is_our_uvicorn() {
  local pid=$1
  [ -z "$pid" ] && return 1
  local args
  args=$(ps -p "$pid" -o args= 2>/dev/null) || return 1
  case "$args" in
    *uvicorn*) return 0 ;;
    *) return 1 ;;
  esac
}

# Kill PIDs on port only if they match the given check (is_our_vite or is_our_uvicorn)
# Sends SIGTERM first; after a short wait, force-kills any still running (stale uvicorn can block restarts)
kill_matching_on_port() {
  local port=$1
  local check=$2  # function name: is_our_vite or is_our_uvicorn
  local pids pid to_kill=""
  pids=$(lsof -ti:"$port" 2>/dev/null)
  for pid in $pids; do
    if [ -n "$pid" ] && "$check" "$pid"; then
      kill "$pid" 2>/dev/null || true
      echo "Stopped process $pid on port $port"
      to_kill="$to_kill $pid"
    fi
  done
  if [ -n "$to_kill" ]; then
    sleep 2
    for pid in $to_kill; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
        echo "Force-killed $pid (was not exiting)"
      fi
    done
  fi
}

# Kill saved PIDs (parent shells)
if [ -f "$PIDS_FILE" ]; then
  while read -r pid; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "Stopped PID $pid"
    fi
  done < "$PIDS_FILE"
  rm -f "$PIDS_FILE"
fi

# Kill processes on our ports only if they match our demo (Vite / uvicorn)
kill_matching_on_port 5173 is_our_vite
kill_matching_on_port 8000 is_our_uvicorn

# Clean up orphaned Vite instances on alternate ports (5174–5199)
port=5174
while [ "$port" -le 5199 ]; do
  pids=$(lsof -ti:"$port" 2>/dev/null)
  for pid in $pids; do
    if [ -n "$pid" ] && is_our_vite "$pid"; then
      kill "$pid" 2>/dev/null || true
      echo "Stopped orphaned Vite process $pid on port $port"
    fi
  done
  port=$((port + 1))
done

echo "Demo stopped."
