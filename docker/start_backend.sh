#!/usr/bin/env sh
set -eu

APP_MODULE="${UVICORN_APP_MODULE:-app.main:app}"
HOST="${UVICORN_HOST:-0.0.0.0}"
PORT="${UVICORN_PORT:-${PORT:-8000}}"
WORKERS="${UVICORN_WORKERS:-1}"
LOG_LEVEL="${UVICORN_LOG_LEVEL:-${LOG_LEVEL:-info}}"
RELOAD="${UVICORN_RELOAD:-false}"
EXTRA_ARGS="${UVICORN_EXTRA_ARGS:-}"

ARGS="--host ${HOST} --port ${PORT} --log-level ${LOG_LEVEL} --proxy-headers --forwarded-allow-ips=*"

# Uvicorn reload is dev-only.
case "${RELOAD}" in
  1|true|TRUE|yes|YES)
    ARGS="${ARGS} --reload"
    ;;
esac

# Only pass --workers when >1 (uvicorn rejects 0).
if [ "${WORKERS}" != "1" ]; then
  ARGS="${ARGS} --workers ${WORKERS}"
fi

if [ -n "${EXTRA_ARGS}" ]; then
  ARGS="${ARGS} ${EXTRA_ARGS}"
fi

echo "[backend] starting: uvicorn ${APP_MODULE} ${ARGS}"
exec uvicorn "${APP_MODULE}" ${ARGS}
