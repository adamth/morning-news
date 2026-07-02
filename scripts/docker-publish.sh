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

: "${DOCKER_IMAGE:?Set DOCKER_IMAGE in .env (e.g. youruser/morning-news)}"

docker build --platform linux/amd64 -t "${DOCKER_IMAGE}:latest" .
docker push "${DOCKER_IMAGE}:latest"

echo "Pushed ${DOCKER_IMAGE}:latest"
