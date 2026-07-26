#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${REDIS_URL:?REDIS_URL is required}"

OUT_PATH="${1:-artifacts/live-core-release-gate.pr.json}"
PRIMARY_PORT="${CI_LIVE_CORE_PRIMARY_PORT:-8000}"
SECONDARY_PORT="${CI_LIVE_CORE_SECONDARY_PORT:-8001}"
PRIMARY_LOG="artifacts/live-core-primary.log"
SECONDARY_LOG="artifacts/live-core-secondary.log"
PRIMARY_TENANT_ID="${CI_LIVE_CORE_PRIMARY_TENANT_ID:-11111111-1111-1111-1111-111111111111}"
SECONDARY_TENANT_ID="${CI_LIVE_CORE_SECONDARY_TENANT_ID:-22222222-2222-2222-2222-222222222222}"
USER_ID="${CI_LIVE_CORE_USER_ID:-ci-live-gate}"

mkdir -p "$(dirname "$OUT_PATH")" artifacts

export ENV="${ENV:-ci}"
export AUTH_MODE="${AUTH_MODE:-header}"
export DEFAULT_TENANT_ID="${DEFAULT_TENANT_ID:-00000000-0000-0000-0000-000000000000}"
export VECTOR_BACKEND="${VECTOR_BACKEND:-faiss}"
export TASK_QUEUE_ENABLED="${TASK_QUEUE_ENABLED:-false}"
export EMBEDDING_CACHE_ENABLED="${EMBEDDING_CACHE_ENABLED:-false}"
export MINIO_ENABLED="${MINIO_ENABLED:-false}"
export LEXICAL_DB_TRGM_ENABLED="${LEXICAL_DB_TRGM_ENABLED:-false}"
export LLM_MOCK_ENABLED="${LLM_MOCK_ENABLED:-true}"
export MIMIRQ_DB_CREATE_ALL_ON_STARTUP="${MIMIRQ_DB_CREATE_ALL_ON_STARTUP:-false}"
export MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED="${MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED:-false}"
export UPLOAD_DEDUP_ENABLED="${UPLOAD_DEDUP_ENABLED:-true}"
# Keep the live core gate isolated from business integrations and startup warmups.
export DIFY_EXTERNAL_KNOWLEDGE_ENABLED="false"
export DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED="false"
export DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY="false"
export RAG_RUNTIME_WARMUP_ENABLED="false"
export RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY="false"
export RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED="${RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED:-true}"
export RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY="${RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY:-3}"
export RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY="${RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY:-3}"
export DATASET_ANALYSIS_PNG_STALE_AFTER_SEC="${DATASET_ANALYSIS_PNG_STALE_AFTER_SEC:-2}"

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
  for pid in "${pids[@]:-}"; do
    wait "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

python -m uvicorn app.main:app --host 127.0.0.1 --port "$PRIMARY_PORT" >"$PRIMARY_LOG" 2>&1 &
pids+=("$!")
python -m uvicorn app.main:app --host 127.0.0.1 --port "$SECONDARY_PORT" >"$SECONDARY_LOG" 2>&1 &
pids+=("$!")

for base_url in "http://127.0.0.1:${PRIMARY_PORT}" "http://127.0.0.1:${SECONDARY_PORT}"; do
  for attempt in $(seq 1 60); do
    if python scripts/api_ping.py --base-url "$base_url" >/dev/null; then
      break
    fi
    if [ "$attempt" -eq 60 ]; then
      echo "[ci-live-core-gate] backend not ready: ${base_url}" >&2
      if [ "$base_url" = "http://127.0.0.1:${PRIMARY_PORT}" ]; then
        cat "$PRIMARY_LOG" >&2 || true
      else
        cat "$SECONDARY_LOG" >&2 || true
      fi
      exit 1
    fi
    sleep 1
  done
done

python scripts/live_core_release_gate.py \
  --base-url "http://127.0.0.1:${PRIMARY_PORT}" \
  --secondary-base-url "http://127.0.0.1:${SECONDARY_PORT}" \
  --tenant-id "$PRIMARY_TENANT_ID" \
  --secondary-tenant-id "$SECONDARY_TENANT_ID" \
  --user-id "$USER_ID" \
  --retrieve-requests "${CI_LIVE_CORE_RETRIEVE_REQUESTS:-4}" \
  --candidate-concurrency "${CI_LIVE_CORE_CANDIDATE_CONCURRENCY:-2}" \
  --min-retrieve-throughput-ratio "${CI_LIVE_CORE_MIN_RETRIEVE_RATIO:-1.0}" \
  --out "$OUT_PATH"
