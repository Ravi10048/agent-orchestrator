#!/usr/bin/env bash
# start.sh — run the Agent Orchestrator dev stack locally (no Docker):
#   backend  :8000   ·   mock API :8001   ·   frontend (Vite — auto-picks a free port)
# Logs + the chosen frontend port are written to .run/. Tear down with ./stop.sh.
# (For the Docker one-command path instead, use ./setup.sh.)
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
RUN="$ROOT/.run"; mkdir -p "$RUN"
UVICORN="$ROOT/backend/.venv/bin/uvicorn"

# ── preflight ───────────────────────────────────────────────────────────
command -v lsof >/dev/null 2>&1 || { echo "✗ 'lsof' is required (used to manage ports)."; exit 1; }
if [ ! -x "$UVICORN" ]; then
  echo "✗ backend venv not found at backend/.venv"
  echo "  setup: cd backend && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "✗ frontend deps not installed."
  echo "  setup: cd frontend && npm install"
  exit 1
fi

free_port() {  # free a port we own (8000/8001) — never touches another app's port
  local pids; pids="$(lsof -ti tcp:"$1" 2>/dev/null)"
  [ -n "$pids" ] && { echo "  · freeing :$1"; kill -9 $pids 2>/dev/null; }
  return 0
}

spawn() {  # spawn NAME DIR CMD…  → background it, log to .run/NAME.log, record the PID
  local name="$1" dir="$2"; shift 2
  ( cd "$dir" && exec "$@" ) >"$RUN/$name.log" 2>&1 &
  echo $! >"$RUN/$name.pid"
}

echo "▶ Starting Agent Orchestrator (native dev)…"
free_port 8000   # backend
free_port 8001   # mock API
# NOTE: we never touch :5173 — if it's taken (e.g. another project), Vite picks the next free port.

spawn backend  "$ROOT/backend"  "$UVICORN" app.main:app --port 8000      # init_db + idempotent seed on startup
spawn mock     "$ROOT/backend"  "$UVICORN" app.mock_api:app --port 8001  # the sample tenant's HTTP tools call this
spawn frontend "$ROOT/frontend" npm run dev                              # Vite dev server (auto-port)

# ── wait for the backend to be healthy ──────────────────────────────────
printf "  · waiting for backend"
for _ in $(seq 1 40); do curl -sf -m2 http://localhost:8000/api/health >/dev/null 2>&1 && break; printf "."; sleep 1; done; echo

# ── detect the frontend's actual port from the Vite log ─────────────────
printf "  · waiting for frontend"
FE_PORT=""
for _ in $(seq 1 40); do
  FE_PORT="$(grep -oE 'localhost:[0-9]+' "$RUN/frontend.log" 2>/dev/null | grep -oE '[0-9]+$' | head -1)"
  [ -n "$FE_PORT" ] && break; printf "."; sleep 1
done; echo
[ -n "$FE_PORT" ] && echo "$FE_PORT" >"$RUN/frontend.port"

echo
echo "✓ Agent Orchestrator is up:"
echo "    frontend  →  http://localhost:${FE_PORT:-5173}      ← open this"
echo "    backend   →  http://localhost:8000    (health: /api/health)"
echo "    mock API  →  http://localhost:8001"
echo
echo "    logs: .run/{backend,mock,frontend}.log     ·     stop: ./stop.sh"
