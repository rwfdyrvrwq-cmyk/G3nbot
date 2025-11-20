#!/bin/bash
# AQW Verification Bot startup helper
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

LOG_DIR="${LOG_DIR:-$PROJECT_ROOT}"
PID_DIR="${PID_DIR:-/tmp}"

mkdir -p "$LOG_DIR" "$PID_DIR"

kill_with_pid_file() {
    local pid_file="$1"
    local label="$2"

    if [ -f "$pid_file" ]; then
        local pid
        pid="$(cat "$pid_file")"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "Stopping existing $label process (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
    fi
}

start_component() {
    local label="$1"
    local log_file="$2"
    local pid_file="$3"
    shift 3

    echo "Starting $label..."
    nohup "$@" > "$log_file" 2>&1 &
    echo $! > "$pid_file"
    echo "✓ $label started (PID $(cat "$pid_file"))"
    echo ""
}

echo "🚀 Starting AQW Verification Bot System"
echo "========================================"

kill_with_pid_file "$PID_DIR/bot.pid" "bot"
kill_with_pid_file "$PID_DIR/scraper.pid" "scraper"

start_component "scraper service" "$LOG_DIR/scraper.log" "$PID_DIR/scraper.pid" \
    "$PYTHON_BIN" "$PROJECT_ROOT/char_data_scraper.py"

start_component "Discord bot" "$LOG_DIR/bot.log" "$PID_DIR/bot.pid" \
    "$PYTHON_BIN" "$PROJECT_ROOT/bot.py"

echo ""
echo "📊 System Status:"
echo "   Scraper Service: see $LOG_DIR/scraper.log"
echo "   Bot: see $LOG_DIR/bot.log"
echo ""
echo "Use 'tail -f <logfile>' for live logs. ✨"
