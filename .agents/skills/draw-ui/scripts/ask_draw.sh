#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${DRAW_VENV:-$HOME/.cache/draw/venv}"
PYTHON_BIN="${DRAW_PYTHON:-$VENV_DIR/bin/python3}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  mkdir -p "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" -c "import google.genai, PIL" >/dev/null 2>&1; then
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install --quiet --upgrade pip google-genai pillow
fi

# --frame <path>: prepend a frame reference image before all other --ref args.
# Usage: ask_draw.sh --frame /path/to/frame.png [other args...]
# This injects --ref <frame> at the front so the frame is always ref[0].
FRAME_PATH=""
REMAINING_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --frame)
      FRAME_PATH="$2"
      shift 2
      ;;
    *)
      REMAINING_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -n "$FRAME_PATH" ]]; then
  exec "$PYTHON_BIN" "$SCRIPT_DIR/generate_image.py" --ref "$FRAME_PATH" "${REMAINING_ARGS[@]}"
else
  exec "$PYTHON_BIN" "$SCRIPT_DIR/generate_image.py" "${REMAINING_ARGS[@]}"
fi
