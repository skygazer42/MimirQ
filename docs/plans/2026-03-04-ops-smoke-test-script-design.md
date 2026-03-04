# Ops Smoke Test Script (Ready -> Ingest -> Structured Query)

**Goal (Ops‑T018):** add a small, purpose-built smoke test script that can be run in CI / post‑deploy verification to prove the “critical path” works end‑to‑end:

1) backend deps are ready (`GET /api/v1/health/ready`)
2) dataset + document ingestion works (`POST /api/v1/datasets/`, `POST /api/v1/documents/upload`, `GET /api/v1/documents/{id}/status`)
3) RAG answering works and can produce **structured JSON output** (`POST /api/v1/chat` with `structured_output=true`)

**Non‑goals:**
- exhaustive OpenAPI coverage (already covered by `scripts/api_smoke.py`)
- load testing / performance (covered by `scripts/rag_e2e_load_test.py`)
- deleting datasets/documents created by the smoke run (can be added later; not required for the signal)

---

## Interface

Script: `scripts/smoke_test.py`

Inputs:
- `--base-url`: accepts either `http://host:8000` or `http://host:8000/api/v1`
- `--tenant-id`: sent as `X-Tenant-ID` (recommended for production)
- Auth auto-detection: `GET /api/v1/meta` → `features.auth_mode`
  - `AUTH_MODE=header`: use `X-User-ID` (`--user-id` or `NEXT_PUBLIC_USER_ID`)
  - `AUTH_MODE=jwt`: require `Authorization: Bearer ...` (`--token` or `MIMIRQ_SMOKE_TOKEN`)
    - optional login bootstrap via `--identifier/--password`
- Optional: `--dataset-id` to reuse an existing dataset (skip dataset creation)
- Structured validation: default **required**; can relax with `--allow-unstructured` for local/dev

Outputs:
- exit code `0` on success; non‑zero on failure
- optional JSON report file via `--out <path>`

PII safety:
- uploads only synthetic content by default (no file reads)
- redacts common secret patterns (`sk-*`, `Bearer ...`) from error output

---

## Core Flow

### 1) Readiness probe (polling)
- Poll `GET /api/v1/health/ready` until:
  - HTTP 200 **and** JSON `{"ok": true, ...}`
  - or `--ready-timeout-sec` elapses (fail)

### 2) Dataset
- If `--dataset-id` provided: reuse
- Else: create a fresh dataset with a random name (avoids collisions), then use its id

### 3) Ingest
- Upload `smoke.txt` containing a unique `SMOKE_FACT: launch_code=<random>` marker.
- Poll `GET /api/v1/documents/{id}/status` until:
  - `status == "completed"` (success)
  - `status == "failed"` (fail)
  - timeout (fail)

### 4) Structured RAG query + validation
- Call `POST /api/v1/chat` with:
  - `document_ids=[<uploaded_doc_id>]`
  - `structured_output=true`
  - `structured_preset=summary` (default)
- Validation (default):
  - response JSON has `structured == true`
  - `structured_data` is a JSON object
  - answer contains the uploaded `launch_code` marker (guards against “LLM answered but retrieval is broken”)

Debugging aid:
- On structured validation failure, best‑effort call `GET /api/v1/settings/status` (if authorized) and include safe status fields (LLM configured/model) in the report.

