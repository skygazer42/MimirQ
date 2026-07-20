#!/usr/bin/env sh
set -e

# Minimal container entrypoint for the FastAPI backend.
# NOTE: This file is referenced by docker/Dockerfile.

: "${HOST:=0.0.0.0}"
: "${PORT:=8000}"
: "${UVICORN_WORKERS:=1}"
: "${UVICORN_LOG_LEVEL:=info}"
: "${FORWARDED_ALLOW_IPS:=127.0.0.1}"

exec uvicorn app.main:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --workers "${UVICORN_WORKERS}" \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS}" \
  --log-level "${UVICORN_LOG_LEVEL}"
