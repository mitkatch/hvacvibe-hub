#!/bin/bash
# ============================================================
# HVAC-Vibe  —  Start script
# Launches FastAPI backend then Chromium in kiosk mode
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Backlight on
echo 1 | sudo tee /sys/class/backlight/backlight_gpio/brightness > /dev/null 2>&1 || true

# Start FastAPI server in background
echo "[hvacvibe] Starting server..."
python3 server.py &
SERVER_PID=$!

# Wait for server to be ready
echo "[hvacvibe] Waiting for server..."
for i in $(seq 1 20); do
  if curl -s http://localhost:8765/ > /dev/null 2>&1; then
    echo "[hvacvibe] Server ready."
    break
  fi
  sleep 0.5
done

# Launch Chromium in kiosk mode
echo "[hvacvibe] Launching Chromium..."
chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --disable-restore-session-state \
  --disable-session-crashed-bubble \
  --disable-translate \
  --disable-features=TranslateUI \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --app=http://localhost:8765/ &
CHROMIUM_PID=$!

# Trap SIGTERM/SIGINT to clean up
cleanup() {
  echo "[hvacvibe] Shutting down..."
  kill $CHROMIUM_PID 2>/dev/null || true
  kill $SERVER_PID   2>/dev/null || true
  exit 0
}
trap cleanup SIGTERM SIGINT

wait $CHROMIUM_PID
kill $SERVER_PID 2>/dev/null || true
