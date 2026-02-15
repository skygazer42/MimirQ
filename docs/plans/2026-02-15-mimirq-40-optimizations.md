# MimirQ 40 Optimizations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve default Docker Compose “one-command” experience for mid-scale usage (5k–50k docs) by delivering 40 concrete optimizations spanning performance/cost + reliability (ingest → retrieval → web → resources).

**Architecture:** Keep existing app architecture. Add a minimal baseline harness + observability hooks, then apply targeted, reversible optimizations behind safe defaults and feature flags. Prefer “fail-closed” behavior for anything affecting auth/scoping/caching.

**Tech Stack:** FastAPI (Python 3.11), LangChain/LangGraph, PostgreSQL, Milvus, Redis (arq), Next.js (web), Docker Compose.

---

## Pre-flight (one-time)

**Step 1: Ensure a clean baseline**

Run:

```bash
git status --porcelain=v1
```

Expected: empty output.

**Step 2: Bring up default stack (optional but recommended)**

Run:

```bash
make init
make up
make ps
```

Expected: postgres/milvus/redis/api healthy.

**Step 3: Run existing quality gates**

Run:

```bash
make verify
```

Expected: PASS.

---

## Phase 0 — Baseline & Metrics (O01–O06)

### Task O01: Add perf harness skeleton (ingest + query)

**Files:**
- Create: `scripts/perf/__init__.py`
- Create: `scripts/perf/run_perf_suite.py`
- Create: `scripts/perf/corpora/sample_manifest.json`
- Create: `scripts/perf/queries/sample_queries.json`
- Create: `scripts/perf/README.md`
- Test: `tests/test_perf_harness_smoke.py`

**Step 1: Write the failing smoke test**

Create `tests/test_perf_harness_smoke.py`:

```python
from pathlib import Path


def test_perf_harness_script_exists():
    path = Path("scripts/perf/run_perf_suite.py")
    assert path.exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_perf_harness_smoke.py`  
Expected: FAIL (file missing).

**Step 3: Write minimal implementation**

Create `scripts/perf/run_perf_suite.py` that:
- Accepts `--out runs/perf/<timestamp>.json`
- Accepts `--base-url` (default `http://localhost:8000`)
- Writes a minimal JSON payload `{ "ts": "...", "suite": "perf-v1" }`

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_perf_harness_smoke.py`  
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/perf tests/test_perf_harness_smoke.py
git commit -m "perf: add baseline perf harness skeleton"
```

### Task O02: Add LLM mock mode support in perf harness (no external calls)

**Files:**
- Modify: `scripts/perf/run_perf_suite.py`
- Modify: `scripts/perf/README.md`
- Test: `tests/test_perf_harness_llm_mock_env.py`

**Step 1: Write failing test**

Create a test asserting perf harness sets `LLM_MOCK_ENABLED=1` when `--llm-mock` is passed.

**Step 2: Verify it fails**

Run: `pytest -q tests/test_perf_harness_llm_mock_env.py`  
Expected: FAIL.

**Step 3: Implement**

In `scripts/perf/run_perf_suite.py`, add:
- `--llm-mock/--no-llm-mock` flag (default true for perf-smoke)
- When enabled, set env var `LLM_MOCK_ENABLED=1` for subprocess calls (or note in output if direct HTTP).

**Step 4: Verify pass**

Run: `pytest -q tests/test_perf_harness_llm_mock_env.py`  
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/perf/run_perf_suite.py tests/test_perf_harness_llm_mock_env.py scripts/perf/README.md
git commit -m "perf: support llm-mock mode in perf harness"
```

### Task O03: Propagate request IDs end-to-end (web → api logs)

**Files:**
- Modify: `web/lib/*` (request client)
- Modify: `app/api/middleware/request_id.py`
- Test: `tests/test_request_id_header_roundtrip.py`

**Step 1: Write failing test**

Create a FastAPI test client that:
- Sends `X-Request-ID: test-123`
- Asserts response echoes/keeps `X-Request-ID: test-123` (or returns in a known header like `X-Request-ID`)

**Step 2: Verify fail**

Run: `pytest -q tests/test_request_id_header_roundtrip.py`  
Expected: FAIL if header not returned.

**Step 3: Implement**

Backend: ensure `RequestIDMiddleware`:
- Accepts inbound `X-Request-ID` if present and valid
- Always sets `X-Request-ID` response header

Frontend: ensure API client:
- Adds `X-Request-ID` per request (uuid) unless already present

**Step 4: Verify pass**

Run: `pytest -q tests/test_request_id_header_roundtrip.py`

**Step 5: Commit**

```bash
git add app/api/middleware/request_id.py web/lib tests/test_request_id_header_roundtrip.py
git commit -m "obs: propagate X-Request-ID across web and api"
```

### Task O04: Add token usage capture for chat + embedding

**Files:**
- Modify: `app/services/*` (LLM call site)
- Modify: `app/rag/*` (embedding call site)
- Modify: `app/models/*` (optional: persist usage)
- Test: `tests/test_usage_capture_mock_llm.py`

**Step 1: Write failing test**

With `LLM_MOCK_ENABLED=1`, call the chat endpoint and assert response includes a `usage` block (even if mocked).

**Step 2: Verify fail**

Run: `pytest -q tests/test_usage_capture_mock_llm.py`  
Expected: FAIL.

**Step 3: Implement**

Standardize a `Usage` dict:

```python
usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "source": "provider|mock|estimate"}
```

Attach to:
- API response (debug/diagnostics fields)
- Best-effort logs/trace

**Step 4: Verify pass**

Run: `pytest -q tests/test_usage_capture_mock_llm.py`  
Expected: PASS.

**Step 5: Commit**

```bash
git add app tests/test_usage_capture_mock_llm.py
git commit -m "obs: capture token usage for chat and embedding"
```

### Task O05: Retrieval channel timing breakdown in debug metrics

**Files:**
- Modify: `app/rag/retriever.py`
- Test: `tests/test_retriever_debug_metrics_shape.py`

**Step 1: Write failing test**

Instantiate `HybridRetriever` with `LLM_MOCK_ENABLED=1` and call retrieval; assert `_last_debug_metrics` contains:
- `timing.vector_ms`
- `timing.bm25_ms`
- `timing.fusion_ms`
- `counts.vector_candidates`
- `counts.bm25_candidates`

**Step 2: Verify fail**

Run: `pytest -q tests/test_retriever_debug_metrics_shape.py`  
Expected: FAIL (keys missing).

**Step 3: Implement**

Add structured metrics emitted by `_hybrid_search` and preserved into `_last_debug_metrics`.

**Step 4: Verify pass**

Run: `pytest -q tests/test_retriever_debug_metrics_shape.py`

**Step 5: Commit**

```bash
git add app/rag/retriever.py tests/test_retriever_debug_metrics_shape.py
git commit -m "obs: add per-channel retrieval timing breakdown"
```

### Task O06: Add `make perf-smoke` target

**Files:**
- Modify: `Makefile`
- Test: `tests/test_makefile_has_perf_smoke_target.py`

**Step 1: Failing test**

Assert `Makefile` contains `perf-smoke:` target.

**Step 2: Verify fail**

Run: `pytest -q tests/test_makefile_has_perf_smoke_target.py`  
Expected: FAIL.

**Step 3: Implement**

Add to `Makefile`:

```makefile
perf-smoke:
	$(PY) scripts/perf/run_perf_suite.py --llm-mock --out runs/perf/perf-smoke.json
```

**Step 4: Verify pass**

Run: `pytest -q tests/test_makefile_has_perf_smoke_target.py`

**Step 5: Commit**

```bash
git add Makefile tests/test_makefile_has_perf_smoke_target.py
git commit -m "perf: add perf-smoke make target"
```

---

## Phase 1 — Docker Defaults: Cost/Reliability (O07–O14)

### Task O07: Add `docker-compose.lite.yml` (low-resource optional profile)

**Files:**
- Create: `docker/docker-compose.lite.yml`
- Modify: `Makefile`
- Modify: `docker/.env.example`
- Docs: `docs/quickstart.md` (or `docs/deployment/docker_compose.md`)

**Step 1: Define acceptance test (manual)**

Run:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.lite.yml config
```

Expected: valid config; lite stack excludes Milvus/etcd/minio (or swaps to Chroma/FAISS).

**Step 2: Implement compose lite**

Create `docker/docker-compose.lite.yml` that:
- Disables Milvus stack
- Enables a local vector backend (Chroma persist or FAISS path)
- Keeps postgres + redis + api (+ worker optional)

**Step 3: Add `make up-lite`**

Add make target that uses both compose files.

**Step 4: Verify**

Run: `make up-lite && make ps`  
Expected: services healthy; ingestion/query works (LLM mock).

**Step 5: Commit**

```bash
git add docker/docker-compose.lite.yml Makefile docker/.env.example docs
git commit -m "docker: add lite compose profile for lower resource usage"
```

### Task O08: Standardize resource knobs via env (cpu/memory-friendly defaults)

**Files:**
- Modify: `docker/docker-compose.yml`
- Modify: `docker/.env.example`

**Step 1: Write a simple config check**

Run:

```bash
docker compose -f docker/docker-compose.yml config > /tmp/mimirq-compose.json
```

Expected: env vars interpolate without errors.

**Step 2: Implement**

Add env-driven settings for:
- Redis maxmemory
- Postgres shared_buffers/work_mem/maintenance_work_mem (compose `command: ["postgres", "-c", "..."]`)

**Step 3: Verify with `docker compose config`**

**Step 4: Commit**

```bash
git add docker/docker-compose.yml docker/.env.example
git commit -m "docker: expose resource tuning knobs via env"
```

### Task O09: Redis memory cap + eviction policy

**Files:**
- Modify: `docker/docker-compose.yml`
- Modify: `docker/.env.example`

**Step 1: Manual acceptance**

Run: `docker exec -it mimirq-redis redis-cli CONFIG GET maxmemory`  
Expected: non-zero when configured.

**Step 2: Implement**

Add `command:` to redis service:

```yaml
command: ["redis-server", "--maxmemory", "${REDIS_MAXMEMORY:-512mb}", "--maxmemory-policy", "${REDIS_MAXMEMORY_POLICY:-allkeys-lru}"]
```

**Step 3: Verify**

**Step 4: Commit**

```bash
git add docker/docker-compose.yml docker/.env.example
git commit -m "docker: cap redis memory and set eviction policy"
```

### Task O10: Postgres mid-scale tuning defaults (safe)

**Files:**
- Modify: `docker/docker-compose.yml`
- Modify: `docker/.env.example`

**Step 1: Define validation**

Run: `docker exec -it mimirq-postgres psql -U postgres -d mimirq -c "SHOW shared_buffers;"`  
Expected: matches env.

**Step 2: Implement**

Add `command:` overrides for selected knobs (conservative defaults).

**Step 3: Verify**

**Step 4: Commit**

```bash
git add docker/docker-compose.yml docker/.env.example
git commit -m "docker: set conservative postgres tuning defaults"
```

### Task O11: Docker log rotation (avoid disk fill)

**Files:**
- Modify: `docker/docker-compose.yml`

**Step 1: Implement**

Add per-service logging:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "${DOCKER_LOG_MAX_SIZE:-10m}"
    max-file: "${DOCKER_LOG_MAX_FILE:-3}"
```

**Step 2: Verify**

Run: `docker inspect mimirq-api --format '{{json .HostConfig.LogConfig}}'`  
Expected: includes max-size/max-file.

**Step 3: Commit**

```bash
git add docker/docker-compose.yml
git commit -m "docker: enable log rotation for services"
```

### Task O12: Worker startup resilience (avoid crash loops on cold start)

**Files:**
- Modify: `app/tasks/worker.py`
- Modify: `app/core/health_checks.py` (if needed)
- Test: `tests/test_worker_startup_logs.py`

**Step 1: Failing test**

Assert worker startup logs a clear message when Redis is unreachable (mock redis settings).

**Step 2: Implement**

Wrap startup in best-effort connectivity check with retry/backoff; do not crash immediately; keep bounded retries.

**Step 3: Verify**

**Step 4: Commit**

```bash
git add app tests/test_worker_startup_logs.py
git commit -m "tasks: improve worker startup resilience and logs"
```

### Task O13: Clarify volume ownership and persistence semantics

**Files:**
- Modify: `docker/docker-compose.yml`
- Modify: `docs/deployment/docker_compose.md`

**Step 1: Implement docs update**

Document which volumes store what and how to reset safely.

**Step 2: Commit**

```bash
git add docker/docker-compose.yml docs/deployment/docker_compose.md
git commit -m "docs(docker): clarify data volumes and persistence semantics"
```

### Task O14: Add compose diagnostics script (`make compose-diagnostics`)

**Files:**
- Create: `scripts/compose_diagnostics.py`
- Modify: `Makefile`
- Test: `tests/test_compose_diagnostics_smoke.py`

**Step 1: Failing test**

Assert script exists and prints JSON with keys: `services`, `health`, `ports`.

**Step 2: Implement**

Script runs:
- `docker compose ps --format json` (fallback parse if needed)
- prints a condensed report

**Step 3: Verify**

Run: `python scripts/compose_diagnostics.py`  
Expected: JSON output.

**Step 4: Commit**

```bash
git add scripts/compose_diagnostics.py Makefile tests/test_compose_diagnostics_smoke.py
git commit -m "ops: add compose diagnostics helper"
```

---

## Phase 2 — Ingest/Parsing/Chunking (O15–O26)

> NOTE: Implement these after Phase 0/1 so we can validate improvements using the perf harness.

### Task O15: Ingest idempotency lock (per dataset + file + pipeline)

**Files:**
- Modify: `app/api/v1/*` (upload endpoint)
- Modify: `app/services/*` (ingest runner)
- Test: `tests/test_ingest_idempotency_lock.py`

**Steps (TDD):**
1. Write failing test that concurrent uploads yield one ingest job.
2. Implement Redis lock (key: tenant+dataset+sha256+pipeline_hash).
3. Ensure lock TTL and release semantics are safe.
4. Verify test passes.
5. Commit: `feat(ingest): add idempotency lock to prevent duplicate ingest`

### Task O16: Accurate progress reporting (stage + percentage)

**Files:**
- Modify: `app/models/document.py`
- Modify: `app/services/*`
- Test: `tests/test_document_progress_stages.py`

**Steps (TDD):**
1. Failing test: progress moves parsing→chunking→embedding→vector_write.
2. Implement progress updates at stage boundaries.
3. Verify.
4. Commit.

### Task O17: Stage checkpointing (resume from last completed stage)

**Files:**
- Modify: `app/services/*`
- Modify: `app/models/document.py` (metadata/checkpoint)
- Test: `tests/test_ingest_checkpoint_resume.py`

**Steps (TDD):**
1. Failing test: simulate failure in embedding; retry resumes without re-parsing.
2. Persist checkpoint state and stage outputs as needed.
3. Verify.
4. Commit.

### Task O18: Parser call wrapper: timeouts/retries/error classes

**Files:**
- Modify: `app/parsing/*`
- Create: `app/parsing/errors.py`
- Test: `tests/test_parser_error_classification.py`

**Steps (TDD):**
1. Failing test: classify timeout vs unsupported file vs internal error.
2. Implement wrapper with bounded retries/backoff.
3. Verify.
4. Commit.

### Task O19: Upload dedup (sha256 + pipeline_hash) (Optional)

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/services/*`
- Test: `tests/test_upload_dedup_returns_existing_document.py`

**Steps (TDD):**
1. Failing test: uploading same file twice returns existing doc id when enabled.
2. Implement dedup lookup + safe constraints/indexes (if needed).
3. Verify.
4. Commit.

### Task O20: Embedding batching + concurrency caps + 429 backoff

**Files:**
- Modify: `app/rag/embedding/*`
- Modify: `app/core/config.py`
- Test: `tests/test_embedding_concurrency_cap.py`

**Steps (TDD):**
1. Failing test: concurrent embedding requests obey cap.
2. Implement semaphore + exponential backoff on 429/5xx.
3. Verify.
4. Commit.

### Task O21: Embedding cache hit/miss metrics

**Files:**
- Modify: `app/rag/embedding/*`
- Modify: `app/services/rag_trace_service.py` (or similar)
- Test: `tests/test_embedding_cache_metrics.py`

**Steps (TDD):**
1. Failing test: cache hit increments counter in metrics.
2. Implement counters (in-memory + optional Prometheus).
3. Verify.
4. Commit.

### Task O22: Adaptive vector write batching

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/storage/vector/*`
- Test: `tests/test_vector_write_batching_adaptive.py`

**Steps (TDD):**
1. Failing test: large docs reduce batch size to avoid spikes.
2. Implement adaptive logic (based on chunk size/count).
3. Verify.
4. Commit.

### Task O23: Parsing peak memory control (streaming/partition)

**Files:**
- Modify: `app/parsing/*`
- Test: `tests/test_large_file_parsing_does_not_load_all_at_once.py`

**Steps (TDD-ish):**
1. Add a regression test with a synthetic large input.
2. Refactor parsing path to stream/chunk.
3. Verify.
4. Commit.

### Task O24: Actionable ingest errors (user-facing hints)

**Files:**
- Modify: `app/core/exceptions.py`
- Modify: `app/services/*`
- Test: `tests/test_ingest_error_hints.py`

**Steps:**
1. Failing test: error response includes `hint` field for known classes.
2. Implement mapping timeout/size/ocr-needed/etc.
3. Verify.
4. Commit.

### Task O25: Safer default worker concurrency for compose

**Files:**
- Modify: `docker/.env.example`
- Modify: `docker/docker-compose.yml`
- Test: `tests/test_default_worker_jobs_is_conservative.py`

**Steps:**
1. Failing test: env default is not overly aggressive (<= 4).
2. Implement defaults + doc note.
3. Verify.
4. Commit.

### Task O26: Precheck-first ingest (Optional)

**Files:**
- Modify: `app/services/dataset_precheck_scan_runner.py`
- Modify: `app/api/v1/*`
- Test: `tests/test_precheck_suggests_pipeline_options.py`

**Steps:**
1. Add tests around precheck suggestions.
2. Add optional flag to run precheck automatically before ingest.
3. Verify.
4. Commit.

---

## Phase 3 — Retrieval latency + token cost (O27–O34)

### Task O27: Enforce scoped retrieval (dataset_id required unless explicit doc_ids)

**Files:**
- Modify: `app/api/v1/*` (chat/query endpoint validation)
- Modify: `app/rag/retriever.py`
- Test: `tests/test_query_requires_dataset_scope.py`

**Steps:**
1. Failing test: query without scope is rejected (400) unless explicitly allowed in dev.
2. Implement validation + safe bypass flag (Optional).
3. Verify.
4. Commit.

### Task O28: Tune top_k/fetch_k/RRF defaults for mid-scale

**Files:**
- Modify: `app/core/config.py`
- Modify: `docker/.env.example`
- Test: `tests/test_retrieval_defaults_are_reasonable.py`

**Steps:**
1. Add tests asserting defaults are within defined safe bounds.
2. Adjust defaults and document trade-offs.
3. Verify.
4. Commit.

### Task O29: BM25 cache invalidation per dataset update

**Files:**
- Modify: `app/rag/retriever.py`
- Modify: `app/services/*` (ingest completion hook)
- Test: `tests/test_bm25_cache_invalidated_on_ingest.py`

**Steps:**
1. Failing test: after ingest new doc, BM25 cache for that dataset invalidates.
2. Implement dataset-level version keying.
3. Verify.
4. Commit.

### Task O30: Retrieval candidate short TTL cache (Optional)

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/rag/retriever.py`
- Test: `tests/test_retrieval_candidate_cache_key_includes_scope.py`

**Steps:**
1. Failing test: cache key includes tenant+dataset+pipeline+account.
2. Implement Redis cache with TTL.
3. Verify.
4. Commit.

### Task O31: Safe chat response cache (Optional, fail-closed)

**Files:**
- Modify: `app/core/config.py`
- Create: `app/services/chat_response_cache.py`
- Modify: `app/api/v1/*`
- Test: `tests/test_chat_response_cache_does_not_cross_scopes.py`

**Steps:**
1. Failing test: different account/dataset never share cached response.
2. Implement cache with strict key + max value bytes.
3. Verify.
4. Commit.

### Task O32: Dynamic model routing (Optional)

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/services/*` (LLM selection)
- Test: `tests/test_dynamic_model_routing_selects_fast_for_simple.py`

**Steps:**
1. Failing test: simple prompt selects fast model; complex selects heavy.
2. Implement routing heuristics.
3. Verify.
4. Commit.

### Task O33: Context compression / de-noising before prompting

**Files:**
- Modify: `app/rag/*` (prompt construction)
- Test: `tests/test_context_dedup_reduces_prompt_tokens.py`

**Steps:**
1. Failing test: duplicate chunks are removed / limited per doc.
2. Implement heuristics: per-doc cap, jaccard dedup, remove boilerplate.
3. Verify.
4. Commit.

### Task O34: Surface latency + token breakdown to web diagnostics

**Files:**
- Modify: `app/api/v1/*` (include debug metrics)
- Modify: `web/app/diagnostics/*`
- Test: `web` vitest for diagnostics render (optional)

**Steps:**
1. Add API fields behind a safe flag (default on for diagnostics endpoint only).
2. Render structured breakdown in `/diagnostics`.
3. Verify locally.
4. Commit.

---

## Phase 4 — Web performance (O35–O40)

### Task O35: Route-level code splitting for heavy deps (monaco/plotly/pdfjs/force-graph)

**Files:**
- Modify: `web/app/**`
- Test: `web` build output (manual) + optional vitest

**Steps:**
1. Identify heavy imports and switch to `next/dynamic`.
2. Verify pages still work.
3. Run: `pnpm -C web run build` (expect success).
4. Commit.

### Task O36: Virtualize large lists (documents/chunks/logs)

**Files:**
- Modify: `web/components/**`
- Test: `web` vitest for list rendering (optional)

**Steps:**
1. Replace large `.map()` lists with `@tanstack/react-virtual`.
2. Verify scrolling and keyboard accessibility.
3. Commit.

### Task O37: Chunk preview render optimization (memoization + visible-first)

**Files:**
- Modify: `web/app/**chunk-preview**`
- Modify: `web/components/**`

**Steps:**
1. Memoize markdown render per chunk id/hash.
2. Render visible region first; defer the rest.
3. Verify scroll smoothness.
4. Commit.

### Task O38: React Query caching + request cancellation/debounce

**Files:**
- Modify: `web/lib/queryClient.ts` (or equivalent)
- Modify: `web/services/**`

**Steps:**
1. Set sane defaults: `staleTime`, `gcTime`, retry rules.
2. Add debounced search and cancel in-flight requests.
3. Commit.

### Task O39: Offload heavy JSON/plot transforms to Web Worker (as needed)

**Files:**
- Create: `web/workers/**`
- Modify: `web/app/reports/**`

**Steps:**
1. Move heavy transform steps to worker using comlink (already a dep).
2. Verify behavior.
3. Commit.

### Task O40: Expand `/diagnostics` with perf and bundle hints

**Files:**
- Modify: `web/app/diagnostics/page.tsx`
- Modify: `web/lib/env.ts` (if needed)

**Steps:**
1. Add sections: API health/ready/meta + timing/token breakdown + quick tips.
2. Keep it safe (no secrets).
3. Commit.

---

## “Definition of Done” for each task

- Has a test or a deterministic verification command.
- Is guarded by safe defaults; optional features are behind explicit env flags.
- Has a small, reversible commit.
- Updates docs/env examples when behavior/config changes.

