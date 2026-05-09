#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/verify_html_mockup.sh \
    --html /path/to/page.html \
    --reference /path/to/mockup.png \
    --out-dir /path/to/verify-output \
    [--viewport 1024x1536] \
    [--full-page] \
    [--session ui-verify]

Opens the HTML in an isolated agent-browser session, captures a viewport
screenshot at the requested viewport, then runs compare_mockup.py. Use
--full-page only when the reference image is also a full-page capture.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTML_PATH=""
REFERENCE_PATH=""
OUT_DIR=""
VIEWPORT="1024x1536"
SESSION="ui-design-verify"
FULL_PAGE=0
CHROME_PATH="${AGENT_BROWSER_EXECUTABLE_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --html)
      HTML_PATH="$2"
      shift 2
      ;;
    --reference)
      REFERENCE_PATH="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --viewport)
      VIEWPORT="$2"
      shift 2
      ;;
    --session)
      SESSION="$2"
      shift 2
      ;;
    --full-page)
      FULL_PAGE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$HTML_PATH" || -z "$REFERENCE_PATH" || -z "$OUT_DIR" ]]; then
  usage >&2
  exit 2
fi

if [[ ! -f "$HTML_PATH" ]]; then
  echo "HTML file not found: $HTML_PATH" >&2
  exit 1
fi

if [[ ! -f "$REFERENCE_PATH" ]]; then
  echo "Reference image not found: $REFERENCE_PATH" >&2
  exit 1
fi

if [[ "$VIEWPORT" != *x* ]]; then
  echo "Viewport must look like 1024x1536" >&2
  exit 2
fi

VIEWPORT_W="${VIEWPORT%x*}"
VIEWPORT_H="${VIEWPORT#*x}"
mkdir -p "$OUT_DIR"

case "$HTML_PATH" in
  file://*)
    URL="$HTML_PATH"
    ;;
  /*)
    URL="file://$HTML_PATH"
    ;;
  *)
    URL="file://$(cd "$(dirname "$HTML_PATH")" && pwd)/$(basename "$HTML_PATH")"
    ;;
esac

SCREENSHOT="$OUT_DIR/browser-screenshot.png"
FULL_SCREENSHOT="$OUT_DIR/browser-full-page.png"

agent-browser \
  --session "$SESSION" \
  --executable-path "$CHROME_PATH" \
  --allow-file-access \
  set viewport "$VIEWPORT_W" "$VIEWPORT_H"

agent-browser \
  --session "$SESSION" \
  --executable-path "$CHROME_PATH" \
  --allow-file-access \
  open "$URL"

if [[ "$FULL_PAGE" -eq 1 ]]; then
  agent-browser \
    --session "$SESSION" \
    --executable-path "$CHROME_PATH" \
    --allow-file-access \
    screenshot "$SCREENSHOT" --full
else
  agent-browser \
    --session "$SESSION" \
    --executable-path "$CHROME_PATH" \
    --allow-file-access \
    screenshot "$SCREENSHOT"

  agent-browser \
    --session "$SESSION" \
    --executable-path "$CHROME_PATH" \
    --allow-file-access \
    screenshot "$FULL_SCREENSHOT" --full
fi

python3 "$SCRIPT_DIR/compare_mockup.py" \
  --reference "$REFERENCE_PATH" \
  --candidate "$SCREENSHOT" \
  --out-dir "$OUT_DIR" \
  --prefix verify
