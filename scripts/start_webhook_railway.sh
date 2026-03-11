#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-src}"
exec uvicorn saleacc_bot.webhook_app:app --host 0.0.0.0 --port "${PORT:-8000}"
