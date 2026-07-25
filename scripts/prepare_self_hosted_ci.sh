#!/usr/bin/env bash
set -euo pipefail

INCLUDE_TORCH_WHEEL_DIR=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --include-torch-wheel-dir)
      INCLUDE_TORCH_WHEEL_DIR=1
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift
done

PY_BIN="${SELF_HOSTED_PYTHON_BIN:-}"
if [ -n "$PY_BIN" ] && [ -d "$PY_BIN" ]; then
  PY_BIN="$PY_BIN/python3.11"
fi
if [ -z "$PY_BIN" ]; then
  PY_BIN="$(command -v python3.11 || command -v python3 || true)"
fi
if [ -z "$PY_BIN" ]; then
  echo "python3.11/python3 not found on self-hosted runner" >&2
  exit 1
fi

VENV_DIR="${SELF_HOSTED_VENV_DIR:-$RUNNER_TEMP/mimirq-py311}"
PIP_CACHE_DIR_VALUE="${PIP_CACHE_DIR:-$RUNNER_TEMP/pip-cache}"
HTTP_PROXY_VALUE="${SELF_HOSTED_HTTP_PROXY:-}"
HTTPS_PROXY_VALUE="${SELF_HOSTED_HTTPS_PROXY:-}"
NO_PROXY_VALUE="127.0.0.1,localhost"
if [ -n "${SELF_HOSTED_NO_PROXY:-}" ]; then
  NO_PROXY_VALUE="$NO_PROXY_VALUE,${SELF_HOSTED_NO_PROXY}"
fi

if [ "$INCLUDE_TORCH_WHEEL_DIR" -eq 1 ]; then
  TORCH_WHEEL_DIR_VALUE="${TORCH_WHEEL_DIR:-$RUNNER_TEMP/torch-wheels}"
  mkdir -p "$(dirname "$VENV_DIR")" "$PIP_CACHE_DIR_VALUE" "$TORCH_WHEEL_DIR_VALUE"
else
  mkdir -p "$(dirname "$VENV_DIR")" "$PIP_CACHE_DIR_VALUE"
fi

"$PY_BIN" -m venv "$VENV_DIR"
echo "$VENV_DIR/bin" >> "$GITHUB_PATH"
{
  echo "PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple}"
  echo "PIP_CACHE_DIR=$PIP_CACHE_DIR_VALUE"
  if [ "$INCLUDE_TORCH_WHEEL_DIR" -eq 1 ]; then
    echo "TORCH_WHEEL_DIR=$TORCH_WHEEL_DIR_VALUE"
  fi
  echo "http_proxy=$HTTP_PROXY_VALUE"
  echo "https_proxy=$HTTPS_PROXY_VALUE"
  echo "HTTP_PROXY=$HTTP_PROXY_VALUE"
  echo "HTTPS_PROXY=$HTTPS_PROXY_VALUE"
  echo "no_proxy=$NO_PROXY_VALUE"
  echo "NO_PROXY=$NO_PROXY_VALUE"
} >> "$GITHUB_ENV"

"$VENV_DIR/bin/python" --version
"$VENV_DIR/bin/pip" --version
