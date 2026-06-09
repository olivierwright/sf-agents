#!/usr/bin/env bash
# start.sh — launch FastAPI backend + Angular dev server in one terminal
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
API_LOG="$ROOT/.api.log"
API_ERR="$ROOT/.api.err.log"

# Kill any leftover process on port 8000
OLD_PID=$(lsof -ti:8000 2>/dev/null || true)
if [[ -n "$OLD_PID" ]]; then
  kill -9 "$OLD_PID" 2>/dev/null || true
  echo "  Cleared stale process on :8000"
fi

# Start FastAPI
PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python" -m uvicorn api.main:app --reload --port 8000 \
  >"$API_LOG" 2>"$API_ERR" &
API_PID=$!
echo "✓ Backend PID $API_PID — tailing $API_LOG"

# Tail both log files to this console in background
tail -f "$API_LOG" "$API_ERR" &
TAIL_PID=$!

cleanup() {
  echo ""
  echo "Stopping backend (PID $API_PID)..."
  kill "$TAIL_PID" 2>/dev/null || true
  kill "$API_PID"  2>/dev/null || true
  rm -f "$API_LOG" "$API_ERR"
}
trap cleanup EXIT INT TERM

# Wait for uvicorn to bind
sleep 4

if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "✗ Backend crashed — last output:"
  tail -30 "$API_LOG" "$API_ERR" 2>/dev/null
  exit 1
fi

# Prewarm connectors
echo "  Prewarming connectors…"
if WARM=$(curl -sf http://localhost:8000/api/warmup); then
  FILES=$(echo "$WARM" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('files_loaded','?'))")
  MS=$(echo "$WARM"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('duration_ms','?'))")
  echo "  ✓ Warm ($FILES files, ${MS}ms)"
else
  echo "  ⚠ Warmup skipped — server may still be starting"
fi

# Start Angular in the foreground (Ctrl+C stops everything via trap)
cd "$ROOT/ui"
npx ng serve --open --proxy-config proxy.conf.json
