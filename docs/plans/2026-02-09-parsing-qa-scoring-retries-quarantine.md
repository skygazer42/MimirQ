# Parsing QA: Quality Scoring, Retries, and Quarantine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Make document parsing "trustworthy by default": every document gets a parse quality score + failure taxonomy, failures are retried deterministically, and low-confidence results are quarantined (not indexed) until resolved. This protects recall precision and prevents garbage chunks from polluting retrieval.

**Non-Goal:** LLM answering. This plan is only about parsing correctness/coverage and the metadata required to drive downstream retrieval SLOs.

**Existing hooks to reuse:**
- Quality scoring: `app/parsing/quality/document_quality.py`
- Dataset profile: `app/services/dataset_profile_service.py` (will display quality distributions)

---

### Task 1: Persist parse quality + failure taxonomy into doc metadata

**Files:**
- Modify: `app/parsing/quality/document_quality.py`
- Modify: `app/parsing/pipeline.py` (or equivalent ingest/parse orchestration)
- Modify: `app/db/models/document.py` (only if new columns are required; prefer metadata JSON)
- Test: `tests/test_parsing_quality_metadata_persisted.py` (new)

**Step 1: Write failing test**

Create `tests/test_parsing_quality_metadata_persisted.py` that:
- Parses a small synthetic document (or mocks parse output)
- Asserts persisted `doc_metadata` contains:
  - `parse_quality.score` (0.0-1.0)
  - `parse_quality.reasons` (list of strings/codes)
  - `parse_quality.version` (bump when heuristics change)
  - `parse_failure.code` (optional when failed/partial)

Run:
```bash
python -m pytest -q tests/test_parsing_quality_metadata_persisted.py
```
Expected: FAIL.

**Step 2: Implement persistence**

Standardize metadata keys:
- `parse_quality: { score: float, reasons: list[str], version: str }`
- `parse_failure: { code: str, detail: str | None }` (only set if failed/partial)

Make sure the writer is idempotent (re-parsing updates these keys deterministically).

**Step 3: Verify**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/parsing/quality/document_quality.py app/parsing/pipeline.py tests/test_parsing_quality_metadata_persisted.py
git commit -m "feat(parsing): persist parse quality score and failure taxonomy"
```

---

### Task 2: Deterministic retry policy + backoff

**Files:**
- Add: `app/parsing/retry_policy.py`
- Modify: `app/parsing/pipeline.py`
- Test: `tests/test_parsing_retry_policy.py` (new)

**Step 1: Write failing tests**

Create tests asserting:
- "transient" failures retry up to N times with backoff
- "permanent" failures do not retry
- retry decisions are based on stable `parse_failure.code` values (not exception strings)

Run:
```bash
python -m pytest -q tests/test_parsing_retry_policy.py
```
Expected: FAIL.

**Step 2: Implement retry policy**

Add `class ParseRetryPolicy` that:
- Maps failure codes to `transient|permanent`
- Computes attempt schedule (e.g., 0s, 10s, 60s) within a max wall time
- Records `parse_attempts` metadata (count, last_attempt_at, last_code)

**Step 3: Verify**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/parsing/retry_policy.py app/parsing/pipeline.py tests/test_parsing_retry_policy.py
git commit -m "feat(parsing): add deterministic retry policy for parse failures"
```

---

### Task 3: Quarantine gate: do not index low-confidence parses by default

**Files:**
- Modify: `app/ingest/indexer.py` (or equivalent chunk/vector indexing entrypoint)
- Modify: `app/core/config.py` (new knobs)
- Test: `tests/test_quarantine_blocks_indexing.py` (new)

**Step 1: Write failing test**

Create a test that:
- Creates a document with `parse_quality.score` below threshold (e.g. 0.4)
- Runs the indexing job
- Asserts no chunks are inserted / no vectors written (or a "quarantined" flag prevents retrieval)

Run:
```bash
python -m pytest -q tests/test_quarantine_blocks_indexing.py
```
Expected: FAIL.

**Step 2: Implement quarantine gate**

Introduce config:
- `PARSING_QUARANTINE_ENABLED=true`
- `PARSING_QUARANTINE_MIN_SCORE=0.60`

Behavior:
- If enabled and score < min: mark doc as quarantined and skip chunk/vector indexing.
- Always retain raw file + parse artifacts for debugging.

**Step 3: Verify**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/ingest/indexer.py app/core/config.py tests/test_quarantine_blocks_indexing.py
git commit -m "feat(parsing): quarantine low-quality parses from indexing"
```

---

### Task 4: Operator UX: surface quarantine and allow re-parse/re-index

**Files:**
- Modify: `app/api/v1/documents.py` (or equivalent)
- Add: `web/app/datasets/[id]/documents/quarantine/page.tsx`
- Test: `tests/test_quarantine_list_endpoint.py` (new)

**Step 1: Add list endpoint (API)**

Add an endpoint to list quarantined docs for a dataset with filters:
- by failure code
- by score range
- by updated_at

**Step 2: Add re-parse + re-index actions**

Expose actions:
- `POST /documents/{id}/reparse`
- `POST /documents/{id}/reindex` (guard: not quarantined)

**Step 3: Minimal UI**

Add a simple page showing quarantined docs with a "reparse" button and the stored reasons/codes.

**Step 4: Commit**

```bash
git add app/api/v1/documents.py web/app/datasets/[id]/documents/quarantine/page.tsx tests/test_quarantine_list_endpoint.py
git commit -m "feat(parsing): quarantine list + reparse UX"
```

