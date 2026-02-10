# Extreme RAG Pipeline Refinement (A/B/15/19/21/F/G) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Push MimirQ's RAG pipeline toward “extreme” engineering quality: every stage (precheck → preprocess → parse → governance → chunk → KG → eval) becomes measurable, explainable, and regression-gated.

**Architecture:** Extend the existing Precheck/Profile/Report services with additional *distribution metrics*, *actionable drill-down*, and *reproducible snapshots*. Keep behavior conservative by default; surface warnings and recommendations via reports/UI/exports, with explicit opt-ins for stronger enforcement where needed.

**Tech Stack:** FastAPI + Pydantic schemas, SQLAlchemy models with JSON summary blobs, Python services under `app/services/`, HTML exporters in `app/services/report_html.py`, Next.js UI pages under `web/app/datasets/[id]/...`, ruff/pytest for quality gates.

---

## Scope (Selected by user)

- **A** Precheck (local folder scan) enhancements
- **B** Preprocess (coarse normalization + routing + observability)
- **15** Parsing provenance completeness
- **19** Governance regex safety hardening
- **21** Chunk distribution target ranges + deviation highlighting
- **F** KG audit + traceability + incremental/dedup stats
- **G** Retrieval-only evaluation slicing + report diff exports

## Deliverables (15 grouped tasks)

### Task 1: Precheck v2 export schema + ext breakdown

**Files:**
- Modify: `app/api/schemas/dataset_precheck.py`
- Modify: `app/services/dataset_precheck_scan_runner.py`
- Modify: `app/api/v1/dataset_precheck.py`
- Test: `tests/test_precheck_*`

**Acceptance:**
- Precheck summary includes versioned export metadata (schema/version).
- Adds richer ext breakdown (top-N + “other” bucket) without breaking old runs.

### Task 2: Precheck usability buckets + drill-down

**Files:**
- Modify: `app/services/dataset_precheck_scan_runner.py`
- Modify: `app/api/schemas/dataset_precheck.py`
- Modify: `web/app/datasets/[id]/precheck/page.tsx` (optional UI surfacing)
- Test: `tests/test_precheck_*`

**Acceptance:**
- Adds actionable buckets: empty/very-short/low-density/gibberish-like.
- Each bucket is drill-downable via existing findings endpoint patterns.

### Task 3: Precheck language distribution (zh/en/mixed/unknown)

**Files:**
- Modify: `app/services/dataset_precheck_scan_runner.py`
- Modify: `app/api/schemas/dataset_precheck.py`
- Modify: `app/services/report_html.py` (precheck HTML section)
- Test: `tests/`

**Acceptance:**
- Computes language bucket from sampled text (best-effort).
- Aggregates into summary + exported HTML.

### Task 4: Precheck spreadsheet + PDF risk distributions

**Files:**
- Modify: `app/services/dataset_precheck_scan_runner.py`
- Modify: `app/api/schemas/dataset_precheck.py`
- Modify: `app/services/report_html.py`
- Test: `tests/`

**Acceptance:**
- Spreadsheet risk counts (large/wide/many-sheets/merged-heavy).
- PDF risk counts (encrypted/no-text/mixed/scanned/low-density where possible).
- Exposes top examples for manual review (best-effort, privacy-safe).

### Task 5: Precheck directory aggregation + drill-down

**Files:**
- Modify: `app/services/dataset_precheck_scan_runner.py`
- Modify: `app/api/schemas/dataset_precheck.py`
- Modify: `app/services/report_html.py`

**Acceptance:**
- Aggregates counts/bytes/risks by directory prefix.
- Can drill down to files under a directory (add endpoint if necessary).

### Task 6: Precheck duplicate clusters + recommendations

**Files:**
- Modify: `app/services/dataset_precheck_scan_runner.py`
- Modify: `app/services/dataset_precheck_service.py`
- Modify: `app/services/report_html.py`
- Test: `tests/`

**Acceptance:**
- Improves exact/near-dup output (clusters + conservative keep/review hints).
- Keeps behavior non-destructive (no auto-delete).

### Task 7: Preprocess normalization ruleset (NFKC/BOM/whitespace)

**Files:**
- Create: `app/services/preprocess_normalization.py` (or similar)
- Modify: parsing entrypoints (upload/preview/chunk-preview) pipeline hook points
- Test: `tests/test_preprocessing_*`

**Acceptance:**
- Optional pre-parse normalization stage with config/pipeline toggle.
- Records what was applied (provenance).

### Task 8: Preprocess failure observability

**Files:**
- Modify: parsing pipeline to capture preprocess errors per file
- Modify: report/provenance schema to expose failure reasons
- Test: `tests/`

**Acceptance:**
- Failures are visible in dataset profile/report findings.

### Task 9: Routing report (per-file route + aggregated stats)

**Files:**
- Modify: parsing pipeline to emit route decisions
- Modify: dataset profile/report aggregation
- Test: `tests/`

**Acceptance:**
- Aggregated route breakdown is visible in dataset report HTML/JSON exports.

### Task 10: Report bundle config snapshot (policy/pipeline/env keys)

**Files:**
- Modify: `app/api/schemas/report.py`
- Modify: `app/services/report_service.py`
- Modify: `app/services/report_html.py`
- Test: `tests/test_reports_*`

**Acceptance:**
- Reports include a reproducible snapshot of key config (safe/redacted).

### Task 11: Parsing provenance completeness (backend/fallback/timings/params/errors)

**Files:**
- Modify: parsing pipeline to persist provenance into document metadata or parsed content table
- Modify: dataset profile aggregation to surface provenance stats
- Test: `tests/`

**Acceptance:**
- For each document: backend used, fallback chain, timings, key params, error summary.

### Task 12: Governance safety hardening (regex limits/timeouts)

**Files:**
- Modify: governance regex compilation/execution layer
- Modify: profile/clean-preview error reporting
- Test: `tests/test_regex_safety.py` and/or governance tests

**Acceptance:**
- Stronger, centralized ReDoS guards and clearer diagnostics for misconfigured rules.

### Task 13: Chunk targets (distribution objectives + deviation highlighting)

**Files:**
- Modify: `app/services/dataset_profile_service.py`
- Modify: `app/services/report_html.py`
- Modify: `web/app/datasets/[id]/profile/page.tsx` (optional)
- Test: `tests/test_dataset_profile_*`

**Acceptance:**
- Adds a “target ranges” section; highlights deviation with reasons/suggestions.

### Task 14: KG audit (metrics + drilldown + incremental/dedup stats)

**Files:**
- Modify: `app/services/report_service.py`
- Modify: KG repositories/services for stats + references
- Modify: `app/api/schemas/report.py`
- Test: `tests/test_dataset_report_html_includes_kg_stats.py` and new KG tests

**Acceptance:**
- KG section becomes traceable (link back to chunk/page) and reports dedup/incremental behavior.

### Task 15: Eval slicing metrics + report diff export

**Files:**
- Modify: evaluation/regression run summary builder
- Create/Modify: report diff exporter (HTML/JSON) comparing two runs
- Test: `tests/`

**Acceptance:**
- Retrieval-only metrics can be sliced by file_type/language/directory buckets.
- Exports a “before vs after” diff artifact for sharing.

