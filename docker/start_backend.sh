#!/usr/bin/env sh
set -e

# Minimal container entrypoint for the FastAPI backend.
# NOTE: This file is referenced by docker/Dockerfile.

: "${HOST:=0.0.0.0}"
: "${PORT:=8000}"
: "${UVICORN_WORKERS:=1}"
: "${UVICORN_LOG_LEVEL:=info}"

exec uvicorn app.main:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --workers "${UVICORN_WORKERS}" \
  --log-level "${UVICORN_LOG_LEVEL}"

