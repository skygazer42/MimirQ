#!/usr/bin/env bash
set -euo pipefail

if command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d --build
else
  docker compose up -d --build
fi

echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8000/docs"
