#!/usr/bin/env bash
set -euo pipefail

# Reproducible "ingestion happy path" demo.
#
# Usage:
#   BASE_URL="http://localhost:8000/api/v1" IDENTIFIER="you@example.com" PASSWORD="..." ./scripts/demo_ingestion_flow.sh
#
# Or provide an existing token:
#   BASE_URL="http://localhost:8000/api/v1" TOKEN="..." ./scripts/demo_ingestion_flow.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
IDENTIFIER="${IDENTIFIER:-${MIMIRQ_DEMO_IDENTIFIER:-}}"
PASSWORD="${PASSWORD:-${MIMIRQ_DEMO_PASSWORD:-}}"
TOKEN="${TOKEN:-${MIMIRQ_DEMO_TOKEN:-}}"
DATASET_NAME="${DATASET_NAME:-demo-$(date +%Y%m%d-%H%M%S)}"
FILE_PATH="${FILE_PATH:-$REPO_ROOT/README.md}"
PARSER_BACKEND="${PARSER_BACKEND:-auto}"
TIMEOUT_SEC="${TIMEOUT_SEC:-600}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-2}"
GOVERNANCE_PROFILE_REF="${GOVERNANCE_PROFILE_REF:-builtin:html_web}"
DRY_RUN="${DRY_RUN:-0}"

json_get() {
  local expr="$1"
  python3 - "$expr" <<'PY'
import json, sys
expr = sys.argv[1]
data = json.load(sys.stdin)
cur = data
for part in expr.split("."):
    if not part:
        continue
    if isinstance(cur, dict):
        cur = cur.get(part)
    else:
        cur = None
        break
print("" if cur is None else cur)
PY
}

echo "[demo] BASE_URL=$BASE_URL"
echo "[demo] FILE_PATH=$FILE_PATH"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[demo] DryRun=ON (no network calls will be made)"
  echo "[demo] dataset_name=$DATASET_NAME"
  echo "[demo] parser_backend=$PARSER_BACKEND"
  echo "[demo] governance_profile_ref=$GOVERNANCE_PROFILE_REF"
  exit 0
fi

if [[ ! -f "$FILE_PATH" ]]; then
  echo "[demo] ERROR: file not found: $FILE_PATH" >&2
  exit 1
fi

if [[ -z "$TOKEN" ]]; then
  if [[ -z "$IDENTIFIER" || -z "$PASSWORD" ]]; then
    echo "[demo] ERROR: provide TOKEN or IDENTIFIER+PASSWORD (or MIMIRQ_DEMO_IDENTIFIER/MIMIRQ_DEMO_PASSWORD)" >&2
    exit 1
  fi
  echo "[demo] Login..."
  login_json="$(curl -fsS "$BASE_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"identifier\": \"${IDENTIFIER}\", \"password\": \"${PASSWORD}\"}")"
  TOKEN="$(printf '%s' "$login_json" | json_get "token.access_token")"
fi

auth=(-H "Authorization: Bearer $TOKEN")

echo "[demo] Create dataset: $DATASET_NAME"
dataset_json="$(curl -fsS "$BASE_URL/datasets/" \
  "${auth[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"${DATASET_NAME}\", \"description\": \"demo (scripted) ingestion flow\"}")"
DATASET_ID="$(printf '%s' "$dataset_json" | json_get "id")"

echo "[demo] Upload document..."
upload_json="$(curl -fsS "$BASE_URL/documents/upload" \
  "${auth[@]}" \
  -F "file=@${FILE_PATH}" \
  -F "dataset_id=${DATASET_ID}" \
  -F "parser_backend=${PARSER_BACKEND}")"
DOC_ID="$(printf '%s' "$upload_json" | json_get "id")"

echo "[demo] document_id=$DOC_ID"

echo "[demo] Poll status..."
deadline=$(( $(date +%s) + TIMEOUT_SEC ))
while true; do
  now=$(date +%s)
  if (( now > deadline )); then
    echo "[demo] ERROR: timeout waiting for completion" >&2
    exit 1
  fi
  st_json="$(curl -fsS "$BASE_URL/documents/${DOC_ID}/status" "${auth[@]}")"
  st="$(printf '%s' "$st_json" | json_get "status")"
  prog="$(printf '%s' "$st_json" | json_get "processing_progress")"
  stage="$(printf '%s' "$st_json" | json_get "current_stage")"
  echo "[demo] status=$st progress=$prog stage=$stage"
  if [[ "$st" == "completed" ]]; then
    break
  fi
  if [[ "$st" == "failed" ]]; then
    echo "[demo] ERROR: document failed" >&2
    exit 1
  fi
  sleep "$POLL_INTERVAL_SEC"
done

echo "[demo] Export ingestion policy snippet for profile: $GOVERNANCE_PROFILE_REF"
out_dir="$REPO_ROOT/runs/demo"
mkdir -p "$out_dir"
safe_key="$(printf '%s' "$GOVERNANCE_PROFILE_REF" | tr -c 'a-zA-Z0-9_.-' '_' )"
out_file="$out_dir/${safe_key}.ingestion_policy.json"
curl -fsS "$BASE_URL/pipeline/governance-profiles/${GOVERNANCE_PROFILE_REF}/export-ingestion-policy" "${auth[@]}" -o "$out_file"
echo "[demo] saved: $out_file"

echo ""
echo "[demo] DONE"
echo "[demo] dataset_id=$DATASET_ID"
echo "[demo] document_id=$DOC_ID"
