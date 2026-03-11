#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill it first."
  exit 1
fi

set -a
. ./.env
set +a

if [[ -z "${GOOGLE_SERVICE_ACCOUNT_JSON_B64:-}" && -z "${GOOGLE_SERVICE_ACCOUNT_JSON:-}" && ! -f keys/google-sa.json ]]; then
  echo "ERROR: Google service account is not configured."
  echo "Use GOOGLE_SERVICE_ACCOUNT_JSON_B64 / GOOGLE_SERVICE_ACCOUNT_JSON or keys/google-sa.json."
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

echo "Deploy: restart webhook container"
compose up -d --no-deps --force-recreate webhook

echo "Deploy done. Active services:"
compose ps
