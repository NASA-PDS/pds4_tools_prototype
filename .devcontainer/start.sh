#!/usr/bin/env bash
# Start backend + frontend dev servers in the background for Codespaces.
set -e
cd "$(dirname "$0")/.."
(cd backend && nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &)
(cd frontend && nohup npm run dev -- --host 0.0.0.0 > /tmp/frontend.log 2>&1 &)
echo "Backend log: /tmp/backend.log  Frontend log: /tmp/frontend.log"
echo "Open the 'PDS4 Viewer' port (5173) from the Ports tab."
