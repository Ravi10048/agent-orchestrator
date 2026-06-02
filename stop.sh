#!/usr/bin/env bash
# stop.sh — stop the Agent Orchestrator dev stack started by ./start.sh
#   (backend :8000 · mock API :8001 · the Vite frontend port recorded in .run/frontend.port).
# Only touches ports this stack owns — your other apps (e.g. :5173) are left running.
set -uo pipefail
cd "$(dirname "$0")"
RUN="$(pwd)/.run"
echo "■ Stopping Agent Orchestrator…"

kill_port() {  # graceful TERM, then force KILL
  local pids; pids="$(lsof -ti tcp:"$1" 2>/dev/null)"
  if [ -n "$pids" ]; then
    echo "  · :$1 → stopping ($pids)"; kill $pids 2>/dev/null; sleep 1; kill -9 $pids 2>/dev/null
  else
    echo "  · :$1 → not running"
  fi
  return 0
}

kill_port 8000   # backend
kill_port 8001   # mock API

FE_PORT="$(cat "$RUN/frontend.port" 2>/dev/null)"
if [ -n "$FE_PORT" ]; then
  kill_port "$FE_PORT"        # our frontend (recorded by start.sh — never assumes :5173 is ours)
else
  echo "  · frontend port unknown — killing the recorded PID if any"
  [ -f "$RUN/frontend.pid" ] && kill -9 "$(cat "$RUN/frontend.pid" 2>/dev/null)" 2>/dev/null || true
fi

rm -f "$RUN"/*.pid "$RUN"/frontend.port 2>/dev/null
echo "✓ Stopped (other apps, e.g. :5173, were left untouched)."
