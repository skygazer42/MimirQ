# Dataset Profile Distributions + Visualization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Make dataset ingestion observable: users can see distribution snapshots (docs/chunks, length, pages, language, parse quality) and quickly drill into outliers via API + UI. Snapshots must be exportable and stable.

**Architecture:** Extend `compute_dataset_profile_summary()` to aggregate additional distributions from `documents` + `document_chunks` + `doc_metadata`, expose in `GET /datasets/{id}/profile/summary`, and render in `web/app/datasets/[id]/profile/page.tsx`. Keep the summary query fast; add separate "drill-down" endpoints for expensive lists (outliers).

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, Next.js/React, recharts, pytest.

---

### Task 1: Add new summary fields (schema)

**Files:**
- Modify: `app/api/schemas/dataset_profile.py`
- Test: `tests/test_dataset_profile_summary_schema_contract.py` (new)

**Step 1: Write the failing test**

Create `tests/test_dataset_profile_summary_schema_contract.py` asserting `DatasetProfileSummary` includes:
- `page_number_histogram` (optional, list of bins like existing `length_histogram`)
- `parse_quality_histogram` (10 bins: 0.0-0.1 ... 0.9-1.0)
- `language_mix` (mapping like `{ "zh": 10, "en": 5, "mixed": 2, "unknown": 1 }`)

Run:
```bash
python -m pytest -q tests/test_dataset_profile_summary_schema_contract.py
```
Expected: FAIL (fields missing).

**Step 2: Implement minimal schema additions**

Update `app/api/schemas/dataset_profile.py`:
- Reuse the existing histogram bin type for the new histograms.
- Add the three new fields to `DatasetProfileSummary`.

**Step 3: Re-run the test**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/api/schemas/dataset_profile.py tests/test_dataset_profile_summary_schema_contract.py
git commit -m "feat(profile): add distribution fields to dataset profile summary schema"
```

---

### Task 2: Compute distributions in dataset_profile_service

**Files:**
- Modify: `app/services/dataset_profile_service.py`
- Modify: `app/services/dataset_profile_utils.py` (only if new bin helpers needed)
- Test: `tests/test_dataset_profile_summary_distributions.py` (new)

**Step 1: Write failing aggregation test (pure)**

Create `tests/test_dataset_profile_summary_distributions.py` that calls an aggregation helper
(e.g. `aggregate_profile_from_rows(...)`) with a small set of synthetic rows and asserts:
- parse quality histogram counts match inputs (from `meta["parse_quality"]["score"]`)
- language mix counts match `meta["language"]` (fallback `unknown`)
- page histogram counts match inputs (from `meta["page_max"]`, if present)

Run:
```bash
python -m pytest -q tests/test_dataset_profile_summary_distributions.py
```
Expected: FAIL until aggregation is implemented.

**Step 2: Implement minimal aggregation**

In `app/services/dataset_profile_service.py`, extend the aggregator to:
- Extract `parse_quality.score` and bucket into 10 bins.
- Extract `language` from doc metadata (normalize to `zh|en|mixed|unknown`).
- Extract `page_max` from doc metadata if present; otherwise leave page histogram empty (do not slow down summary by scanning chunks).

**Step 3: Re-run test**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/services/dataset_profile_service.py app/services/dataset_profile_utils.py tests/test_dataset_profile_summary_distributions.py
git commit -m "feat(profile): compute language/quality/page distributions in summary"
```

---

### Task 3: Backfill missing metadata needed by charts (deep scan runner)

**Files:**
- Modify: `app/services/dataset_profile_scan_runner.py`
- Modify (optional): `app/parsing/processors/processor.py` (set page_max at ingest time when available)
- Test: `tests/test_dataset_profile_scan_backfills_page_max_and_language.py` (new)

**Step 1: Write failing unit tests**

Add a test that:
- Starts with `doc_metadata={}` and a mocked parse result containing `page_count` / `page_max`
- Calls a new helper (e.g. `_backfill_page_max(meta, parsed)`), expects `meta["page_max"]=...`
- Calls a new helper for language (or reads existing governance metadata), expects `meta["language"]` to be set or remain `unknown`

Run:
```bash
python -m pytest -q tests/test_dataset_profile_scan_backfills_page_max_and_language.py
```
Expected: FAIL (helpers missing).

**Step 2: Implement best-effort backfill**

In `app/services/dataset_profile_scan_runner.py`:
- `_backfill_page_max(meta, parsed)` pulls max/page_count from parse artifacts if present.
- `_backfill_language(meta)`:
  - If `meta["language"]` exists: no-op
  - Else: set `"unknown"` (do not guess in the profiler; language detection belongs to parsing/governance)

**Step 3: Re-run test**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/services/dataset_profile_scan_runner.py app/parsing/processors/processor.py tests/test_dataset_profile_scan_backfills_page_max_and_language.py
git commit -m "feat(profile): backfill page_max and language metadata for profiling"
```

---

### Task 4: UI: render new charts + outlier drill-down entry points

**Files:**
- Modify: `web/app/datasets/[id]/profile/page.tsx`
- Test: `web/app/datasets/[id]/profile/page.test.tsx` (new or extend existing)

**Step 1: Write lightweight UI test**

Add a test that renders the page with a stub `DatasetProfileSummary` containing:
- `parse_quality_histogram`
- `language_mix`
and asserts the new sections render (e.g. section headings exist).

Run:
```bash
pnpm -C web test --filter dataset-profile
```
Expected: FAIL until UI is updated.

**Step 2: Implement UI sections**

In `web/app/datasets/[id]/profile/page.tsx`:
- Add a "Parse Quality" histogram chart.
- Add a "Language Mix" chart.
- Add a "Pages" histogram chart when `page_number_histogram` is non-empty.
- Add links/buttons for outlier drill-down (top N longest docs, lowest parse quality docs).

**Step 3: Re-run UI test**

Expected: PASS.

**Step 4: Commit**

```bash
git add web/app/datasets/[id]/profile/page.tsx web/app/datasets/[id]/profile/page.test.tsx
git commit -m "feat(web): add parse quality / language / page distribution charts"
```

---

### Task 5: Export snapshots (API)

**Files:**
- Modify: `app/api/v1/datasets.py` (ensure export includes new fields)
- Test: `tests/test_dataset_profile_export_includes_new_fields.py` (new)

**Step 1: Write failing test**

Call the export handler (or service) and assert JSON contains the new keys.

Run:
```bash
python -m pytest -q tests/test_dataset_profile_export_includes_new_fields.py
```
Expected: FAIL.

**Step 2: Implement**

Ensure the export path returns the updated schema output without dropping fields.

**Step 3: Verify**

Run:
```bash
python -m pytest -q
```
Expected: PASS.

**Step 4: Commit**

```bash
git add app/api/v1/datasets.py tests/test_dataset_profile_export_includes_new_fields.py
git commit -m "feat(profile): export includes new distribution fields"
```

