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

: "${DOCKER_IMAGE:?Set DOCKER_IMAGE in .env (e.g. youruser/morning-news:latest)}"

COMPOSE_FILE="${ROOT}/docker-compose.unraid.yml"
if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing ${COMPOSE_FILE}" >&2
  exit 1
fi

docker compose -f "${COMPOSE_FILE}" pull
docker compose -f "${COMPOSE_FILE}" up -d

echo "Updated ${DOCKER_IMAGE} — data directory: ${APP_DATA_DIR:-/mnt/user/appdata/morning-news}"
