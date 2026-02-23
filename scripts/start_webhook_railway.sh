#!/usr/bin/env bash
set -euo pipefail

prepare_google_sa() {
  local target_file="${GOOGLE_SERVICE_ACCOUNT_FILE:-/tmp/google-sa.json}"

  if [[ -n "${GOOGLE_SERVICE_ACCOUNT_JSON_B64:-}" ]]; then
    printf '%s' "${GOOGLE_SERVICE_ACCOUNT_JSON_B64}" | base64 -d > "${target_file}"
    export GOOGLE_SERVICE_ACCOUNT_FILE="${target_file}"
    return
  fi

  if [[ -n "${GOOGLE_SERVICE_ACCOUNT_JSON:-}" ]]; then
    printf '%s' "${GOOGLE_SERVICE_ACCOUNT_JSON}" > "${target_file}"
    export GOOGLE_SERVICE_ACCOUNT_FILE="${target_file}"
    return
  fi

  if [[ -n "${GOOGLE_SERVICE_ACCOUNT_FILE:-}" && -f "${GOOGLE_SERVICE_ACCOUNT_FILE}" ]]; then
    return
  fi

  echo "ERROR: Google service account is not configured."
  echo "Set GOOGLE_SERVICE_ACCOUNT_JSON_B64 or GOOGLE_SERVICE_ACCOUNT_JSON."
  exit 1
}

prepare_google_sa
export PYTHONPATH="${PYTHONPATH:-src}"
exec uvicorn saleacc_bot.webhook_app:app --host 0.0.0.0 --port "${PORT:-8000}"

