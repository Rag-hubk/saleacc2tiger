#!/usr/bin/env zsh
set -euo pipefail

PATTERN="saleacc_bot.main"
pkill -f "$PATTERN" >/dev/null 2>&1 || true
sleep 0.3
if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  pkill -9 -f "$PATTERN" >/dev/null 2>&1 || true
fi
echo "Stopped all local bot processes."
