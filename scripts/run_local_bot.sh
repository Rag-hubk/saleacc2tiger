#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${0}")/.." && pwd)"
cd "$ROOT_DIR"

# Always run only one latest local process.
PATTERN="saleacc_bot.main"
pkill -f "$PATTERN" >/dev/null 2>&1 || true
sleep 0.3
if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  pkill -9 -f "$PATTERN" >/dev/null 2>&1 || true
fi

echo "Starting local bot (single instance)..."
exec env PYTHONPATH=src python3 -m saleacc_bot.main
