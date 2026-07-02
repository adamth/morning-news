#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
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

exec "${UVICORN}" app.main:app --reload --port "${PORT:-8080}"
