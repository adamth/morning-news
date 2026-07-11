#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# Local dev pulls secrets from Infisical (see .infisical.json). Falls back to
# .env so the script still works without the CLI. Docker deploys don't use this
# script and keep reading .env via compose.
USE_INFISICAL=0
if command -v infisical >/dev/null 2>&1; then
  USE_INFISICAL=1
elif [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "infisical CLI not found and no .env file present; starting without secrets" >&2
fi

export DATA_DIR="${DATA_DIR:-./data}"

if [[ -x "${ROOT}/.venv/bin/uvicorn" ]]; then
  UVICORN="${ROOT}/.venv/bin/uvicorn"
elif command -v uvicorn >/dev/null 2>&1; then
  UVICORN="uvicorn"
else
  echo "uvicorn not found. Create a venv and pip install -r requirements.txt" >&2
  exit 1
fi

npm run build:css

npm run watch:css &
CSS_PID=$!
trap 'kill "${CSS_PID}" 2>/dev/null || true' EXIT INT TERM

if [[ "${USE_INFISICAL}" -eq 1 ]]; then
  exec infisical run -- "${UVICORN}" app.main:app --reload --port "${PORT:-8080}"
fi
exec "${UVICORN}" app.main:app --reload --port "${PORT:-8080}"
