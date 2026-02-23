#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill it first."
  exit 1
fi

if [[ ! -f keys/google-sa.json ]]; then
  echo "ERROR: keys/google-sa.json not found."
  echo "Put your Google service account key here: keys/google-sa.json"
  exit 1
fi

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1 && sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose "$@"
    return
  fi
  echo "ERROR: docker compose is not available."
  exit 1
}

echo "Deploy: build image"
compose build --pull bot

echo "Deploy: init Google Sheet schema"
compose run --rm bot env PYTHONPATH=src python3 scripts/init_google_sheet.py

echo "Deploy: restart single bot container"
compose up -d --no-deps --force-recreate bot

if [[ "${ENABLE_WEBHOOK:-0}" == "1" ]]; then
  echo "Deploy: webhook profile is enabled"
  compose up -d --no-deps --force-recreate webhook
fi

echo "Deploy done. Active services:"
compose ps
