#!/usr/bin/env bash
# Start the backend (port 8000) and frontend dev server (port 5173) in the background.
# Runs each time the codespace is attached; servers already running are left alone.
set -e
cd "$(dirname "$0")/.."
export PDS_LOCAL_ROOT="${PDS_LOCAL_ROOT:-$PWD/test_data}"

running() { curl -s -o /dev/null --max-time 2 "$1"; }

if running http://127.0.0.1:8000/api/health; then
  echo "Backend already running on :8000"
else
  (cd backend && nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &)
  echo "Started backend (log: /tmp/backend.log)"
fi

if running http://127.0.0.1:5173/; then
  echo "Frontend already running on :5173"
else
  (cd frontend && nohup npm run dev -- --host 0.0.0.0 > /tmp/frontend.log 2>&1 &)
  echo "Started frontend (log: /tmp/frontend.log)"
fi

for _ in $(seq 1 30); do
  if running http://127.0.0.1:8000/api/health && running http://127.0.0.1:5173/; then
    echo "PDS4 Viewer is ready: open the 'PDS4 Viewer' port (5173) from the Ports tab."
    exit 0
  fi
  sleep 1
done
echo "Servers are still starting; check /tmp/backend.log and /tmp/frontend.log."
