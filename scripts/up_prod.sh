#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  cp .env.prod.example .env
  echo "[env] created: .env (from .env.prod.example)"
else
  echo "[env] exists: .env"
fi

if [[ "${1:-}" == "--web" ]]; then
  docker compose -f docker-compose.prod.yml --profile web up -d --build
else
  docker compose -f docker-compose.prod.yml up -d --build
fi

docker compose -f docker-compose.prod.yml ps

