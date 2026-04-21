# RAG Attribution And Analysis Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn `plans/rag-poc-attribution-framework-2026-q2.md` into production-grade backend analysis capabilities for the full RAG system, with dataset-scoped APIs, exports, attribution, coverage analysis, and glossary-backed domain rule bootstrapping.

**Architecture:** Reuse the existing `rag_trace` / `retrieval_trace` records as the primary interaction source and treat `MessageFeedback` as a coverage/enrichment layer. Keep the analysis core in `app/rag/evaluation/poc_runner/` as pure, injectable modules, then expose dataset-scoped APIs for structured data, HTML reports, JSON/JSONL export, and asynchronous PNG generation.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, existing `app/api/v1/feedback.py`, `app/models/feedback.py`, `app/services/rag_trace_service.py`, pytest, `pyecharts` for HTML reports, a minimal async task result path for PNG export.

---

## Confirmed Product Decisions

- This work is for a complete RAG system, not a POC or MVP.
- Preserve the attribution/analysis direction as a system capability.
- Reuse existing `MessageFeedback + retrieval_trace` instead of creating a second telemetry store.
- Keep an independent `telemetry.py` normalization layer.
- `rag_trace` is the primary source for `all_interactions`; `feedback` is the enrichment/coverage layer.
- First version telemetry/reporting must include all interactions, not only rows with feedback.
- Attribution categories stay limited to `retrieval_miss`, `generation_error`, `out_of_scope`.
- Attribution is pluggable, but Batch A only ships a rules/heuristics implementation.
- Attribution runs only on negative feedback rows.
- Low-confidence attribution outputs only `manual_review_candidates`; no review workflow/state machine yet.
- `out_of_scope` is a separate capability with a three-stage, configurable structure.
- Batch A does not change the online answering path; `out_of_scope` is analysis-only for now.
- `query_pattern_miner` is kept and Batch A uses the lightweight version.
- `query_pattern_miner` outputs glossary candidates, but does not auto-write back.
- `industry_rules` stays, but Batch A only ships the glossary-focused bootstrap module and sample ruleset.
- First ruleset is `industrial_control` as a bootstrap sample.
- `industry_rules` API is not part of the first version.
- Reports must preserve the five core metrics plus feedback coverage.
- Report outputs must include structured data + HTML (`pyecharts`) + export APIs.
- Export formats for this MD are `JSON + JSONL + HTML + PNG`.
- `JSON/JSONL/HTML` are synchronous; `PNG` uses a minimal async task result model.
- APIs are dataset-scoped paths, not top-level generic endpoints.
- Aggregation APIs are not paginated; sample/detail endpoints support `limit`.
- Coverage heatmap in the first version is document/file heat, with both citation heat and negative-feedback heat.
- `PNG` support includes the full report, not only a single chart.
- Reports must keep top examples, ranked by high confidence + recentness.
- APIs and exported artifacts must carry filters, scope metadata, schema/version, and definitions.
- Build this MD in two implementation batches.

## Explicitly Not In This MD

- `app/rag/demo/poc_streamlit.py`
- `app/api/v1/industry_rules.py`
- Automatic glossary write-back from `query_pattern_miner`
- LLM-based attribution classifier
- Wiring `out_of_scope` into the live answering pipeline
- UMAP scatter support in the first version
- A generic export/job platform beyond the minimal PNG async model

## API Shape To Preserve

- Dataset scope is explicit in the route path.
- Prefer route families like:
  - `/api/v1/datasets/{dataset_id}/analysis/summary`
  - `/api/v1/datasets/{dataset_id}/analysis/examples`
  - `/api/v1/datasets/{dataset_id}/analysis/coverage-heatmap`
  - `/api/v1/datasets/{dataset_id}/analysis/report.html`
  - `/api/v1/datasets/{dataset_id}/analysis/export.json`
  - `/api/v1/datasets/{dataset_id}/analysis/export.jsonl`
  - `/api/v1/datasets/{dataset_id}/analysis/export.png`
  - `/api/v1/datasets/{dataset_id}/analysis/export-tasks/{task_id}`

## Shared Rules For Every Task

- [ ] Follow TDD: write the test first, confirm it fails, then implement the minimum code.
- [ ] Keep the analysis core pure/injectable before wiring APIs.
- [ ] Reuse existing trace/feedback fields; do not invent parallel storage unless a task explicitly requires a cache or task result row.
- [ ] Keep schemas bounded, deterministic, and explicit.
- [ ] Update this file from `[ ]` to `[x]` as each task is verified complete.
- [ ] After finishing Batch A, stop and review before starting Batch B.

## Batch A: Core Analysis Capabilities

### Task A1: Telemetry Normalization

**Files:**
- Create: `app/rag/evaluation/poc_runner/__init__.py`
- Create: `app/rag/evaluation/poc_runner/telemetry.py`
- Test: `tests/test_poc_runner_telemetry.py`

**Deliverable:**
- Dataset-scoped normalization of trace + feedback into stable analysis rows.
- Output row schema must support:
  - `all_interactions`
  - `feedback_interactions`
  - `attributable_feedback_interactions`
- Required normalized fields:
  - interaction/request identifiers
  - dataset/conversation/message linkage
  - question text
  - answer text
  - file/document hit list
  - feedback score/reason when present
  - timestamps
  - trace latency summary when present
  - `has_feedback`
  - `request_id`-first linkage metadata

- [ ] Step 1: Write failing tests for `build_poc_interaction_row(...)` and dataset-row aggregation.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_telemetry.py` and confirm the module/function is missing or wrong.
- [ ] Step 3: Implement the minimum normalization module and schema constants.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_telemetry.py` until green.
- [ ] Step 5: Commit the task.

### Task A2: Dataset Analysis Source Builder

**Files:**
- Create: `app/rag/evaluation/poc_runner/source_builder.py`
- Test: `tests/test_poc_runner_source_builder.py`

**Deliverable:**
- A dataset-scoped builder that merges:
  - trace rows as the primary interaction base
  - feedback rows as the enrichment layer
- Link strategy:
  - primary: `request_id`
  - fallback: conservative `message_id`, then `conversation_id`
- Must output explicit counts for:
  - all interactions
  - feedback interactions
  - attributable negative-feedback interactions

- [ ] Step 1: Write failing tests for `request_id` primary linking and conservative fallback linking.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_source_builder.py` and confirm red.
- [ ] Step 3: Implement the merge logic with conservative conflict handling.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_source_builder.py` until green.
- [ ] Step 5: Commit the task.

### Task A3: Rules/Heuristics Attribution Classifier

**Files:**
- Create: `app/rag/evaluation/poc_runner/attribution_classifier.py`
- Test: `tests/test_poc_runner_attribution_classifier.py`

**Deliverable:**
- Pluggable attribution interface.
- First implementation is rules/heuristics only.
- Operates only on negative-feedback rows.
- Output includes:
  - category counts
  - ratios
  - top examples
  - `manual_review_candidates`
- Top example ordering:
  - mixed weighting of confidence + recentness

- [ ] Step 1: Write failing tests for negative-only classification, manual review candidates, and mixed example ordering.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_attribution_classifier.py` and confirm red.
- [ ] Step 3: Implement the pluggable interface plus the default heuristic classifier.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_attribution_classifier.py` until green.
- [ ] Step 5: Commit the task.

### Task A4: Configurable Out-Of-Scope Verifier

**Files:**
- Create: `app/rag/evaluation/poc_runner/out_of_scope_verifier.py`
- Test: `tests/test_poc_runner_out_of_scope_verifier.py`

**Deliverable:**
- Independent verifier with a three-stage structure:
  - keyword-expanded hit check
  - vector top-score check
  - optional HyDE fallback check
- Configurable/cuttable execution path.
- Output verdict:
  - `in_scope`
  - `ambiguous`
  - `out_of_scope`
- This module remains analysis-only in Batch A.

- [ ] Step 1: Write failing tests for all three stages, cropped execution, and verdict rules.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_out_of_scope_verifier.py` and confirm red.
- [ ] Step 3: Implement the verifier with injectable search/generation hooks.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_out_of_scope_verifier.py` until green.
- [ ] Step 5: Commit the task.

### Task A5: Query Pattern Miner

**Files:**
- Create: `app/rag/evaluation/poc_runner/query_pattern_miner.py`
- Test: `tests/test_poc_runner_query_pattern_miner.py`

**Deliverable:**
- Lightweight pattern mining only:
  - abbreviation detection
  - multi-intent detection
  - keyword weighting
  - document/file heat candidates
- Emit glossary candidate suggestions, but do not auto-write them anywhere.

- [ ] Step 1: Write failing tests for abbreviation detection, multi-intent detection, and glossary candidate output.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_query_pattern_miner.py` and confirm red.
- [ ] Step 3: Implement the lightweight miner.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_query_pattern_miner.py` until green.
- [ ] Step 5: Commit the task.

### Task A6: Industry Rules Bootstrap (Glossary Version)

**Files:**
- Create: `app/rag/industry_rules/__init__.py`
- Create: `app/rag/industry_rules/schema.py`
- Create: `app/rag/industry_rules/loaders/__init__.py`
- Create: `app/rag/industry_rules/loaders/yaml_loader.py`
- Create: `app/rag/industry_rules/appliers/__init__.py`
- Create: `app/rag/industry_rules/appliers/query_rewrite.py`
- Create: `app/rag/industry_rules/rulesets/industrial_control/glossary.yaml`
- Optionally create empty placeholder files for `patterns.yaml` and `intents.yaml` if needed for loader completeness
- Test: `tests/test_industry_rules_bootstrap.py`

**Deliverable:**
- Bootstrap sample ruleset for `industrial_control`
- Loader + schema + glossary expansion
- No `industry_rules` API yet
- No deep main-orchestrator wiring yet

- [ ] Step 1: Write failing tests for loading the sample ruleset and glossary expansion behavior.
- [ ] Step 2: Run `pytest -q tests/test_industry_rules_bootstrap.py` and confirm red.
- [ ] Step 3: Implement the glossary-first bootstrap module.
- [ ] Step 4: Re-run `pytest -q tests/test_industry_rules_bootstrap.py` until green.
- [ ] Step 5: Commit the task.

### Task A7: Core Metrics And Aggregation Summary

**Files:**
- Create: `app/rag/evaluation/poc_runner/metrics.py`
- Test: `tests/test_poc_runner_metrics.py`

**Deliverable:**
- Compute and expose:
  - raw positive rate
  - controllable positive rate
  - knowledge-base coverage
  - retrieval accuracy
  - generation accuracy
  - feedback coverage rate
- Metrics must be dataset-scoped and filter-aware.
- Metrics must preserve definitions for `all_interactions`, `feedback_interactions`, and `attributable_feedback_interactions`.

- [ ] Step 1: Write failing tests for all five core metrics plus feedback coverage.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_metrics.py` and confirm red.
- [ ] Step 3: Implement the metrics helper.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_metrics.py` until green.
- [ ] Step 5: Commit the task.

### Task A8: Dataset-Scoped Analysis Data APIs

**Files:**
- Modify or create: `app/api/v1/datasets_analysis.py` or the repo-consistent equivalent under `app/api/v1/`
- Modify: `app/api/v1/__init__.py`
- Create schemas as needed under `app/api/schemas/`
- Test: `tests/test_dataset_analysis_api.py`

**Deliverable:**
- Dataset-scoped, split APIs, not a single universal endpoint.
- Batch A APIs should cover:
  - summary/metrics
  - top examples
  - manual review candidates
  - glossary candidates / pattern miner output
- Rules:
  - `dataset_id` is path-scoped
  - minimal filters supported
  - aggregate endpoints do not paginate
  - sample/detail endpoints support `limit`
  - every response includes `meta` with filters, scope, generated time, schema, and definitions

- [ ] Step 1: Write failing API tests for dataset scoping, minimal filters, and `meta`.
- [ ] Step 2: Run `pytest -q tests/test_dataset_analysis_api.py` and confirm red.
- [ ] Step 3: Implement the dataset-scoped data APIs.
- [ ] Step 4: Re-run `pytest -q tests/test_dataset_analysis_api.py` until green.
- [ ] Step 5: Commit the task.

### Task A9: JSON And JSONL Export APIs

**Files:**
- Extend: dataset analysis API module from Task A8
- Test: `tests/test_dataset_analysis_export_api.py`

**Deliverable:**
- Synchronous export endpoints for:
  - aggregate JSON report
  - JSONL normalized rows / candidate details
- Must preserve `meta` and filter summary.

- [ ] Step 1: Write failing export API tests for JSON and JSONL outputs.
- [ ] Step 2: Run `pytest -q tests/test_dataset_analysis_export_api.py` and confirm red.
- [ ] Step 3: Implement synchronous JSON/JSONL export endpoints.
- [ ] Step 4: Re-run `pytest -q tests/test_dataset_analysis_export_api.py` until green.
- [ ] Step 5: Commit the task.

### Batch A Verification Gate

- [ ] Run the complete Batch A targeted suite.

  ```bash
  pytest -q \
    tests/test_poc_runner_telemetry.py \
    tests/test_poc_runner_source_builder.py \
    tests/test_poc_runner_attribution_classifier.py \
    tests/test_poc_runner_out_of_scope_verifier.py \
    tests/test_poc_runner_query_pattern_miner.py \
    tests/test_industry_rules_bootstrap.py \
    tests/test_poc_runner_metrics.py \
    tests/test_dataset_analysis_api.py \
    tests/test_dataset_analysis_export_api.py
  ```

- [ ] Run a focused router/import smoke test if new API modules were registered.

  ```bash
  pytest -q tests/test_api_v1_lazy_router_import.py
  ```

- [ ] Update `docs/plans/2026-04-21-backend-plan-execution-roadmap.md` for the first source MD after Batch A is verified.

## Batch B: Reports, Heatmaps, And PNG Export

### Task B1: Coverage Heatmap Aggregation

**Files:**
- Create: `app/rag/evaluation/poc_runner/coverage_heatmap.py`
- Test: `tests/test_poc_runner_coverage_heatmap.py`

**Deliverable:**
- Document/file heat aggregation only.
- First version dimensions:
  - citation heat
  - negative-feedback heat
- No theme-by-document matrix yet.

- [ ] Step 1: Write failing tests for citation heat + negative feedback heat aggregation.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_coverage_heatmap.py` and confirm red.
- [ ] Step 3: Implement the heat aggregation module.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_coverage_heatmap.py` until green.
- [ ] Step 5: Commit the task.

### Task B2: Structured Report Builder

**Files:**
- Create: `app/rag/evaluation/poc_runner/reports/__init__.py`
- Create: `app/rag/evaluation/poc_runner/reports/attribution_report.py`
- Test: `tests/test_poc_runner_attribution_report.py`

**Deliverable:**
- Assemble:
  - metrics
  - category counts
  - top examples
  - manual review candidates
  - glossary candidate summary
  - coverage heatmap payload
  - filters / definitions / schema metadata

- [ ] Step 1: Write failing report-builder tests.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_attribution_report.py` and confirm red.
- [ ] Step 3: Implement the structured report builder.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_attribution_report.py` until green.
- [ ] Step 5: Commit the task.

### Task B3: HTML Report Rendering With Pyecharts

**Files:**
- Create: `app/rag/evaluation/poc_runner/reports/html_renderer.py`
- Test: `tests/test_poc_runner_html_report.py`

**Deliverable:**
- Synchronous HTML report rendering using `pyecharts`
- Must include:
  - report metadata / filters
  - core metrics
  - attribution summary
  - top examples
  - coverage heatmap

- [ ] Step 1: Write failing tests for HTML report generation and presence of key sections.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_html_report.py` and confirm red.
- [ ] Step 3: Implement the HTML report renderer.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_html_report.py` until green.
- [ ] Step 5: Commit the task.

### Task B4: Dataset Report HTML API

**Files:**
- Extend: dataset analysis API module
- Test: `tests/test_dataset_analysis_html_api.py`

**Deliverable:**
- Synchronous dataset-scoped HTML report endpoint
- Returns full report HTML

- [ ] Step 1: Write failing API tests for HTML report output.
- [ ] Step 2: Run `pytest -q tests/test_dataset_analysis_html_api.py` and confirm red.
- [ ] Step 3: Implement the HTML report endpoint.
- [ ] Step 4: Re-run `pytest -q tests/test_dataset_analysis_html_api.py` until green.
- [ ] Step 5: Commit the task.

### Task B5: Minimal PNG Export Task Model

**Files:**
- Create: `app/rag/evaluation/poc_runner/png_tasks.py` or repo-consistent equivalent
- Create minimal persistence model only if needed
- Test: `tests/test_poc_runner_png_tasks.py`

**Deliverable:**
- Minimal async result model for PNG only:
  - create task
  - get status
  - get result
- Not a general-purpose job platform

- [ ] Step 1: Write failing tests for task creation, status transitions, and result retrieval.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_png_tasks.py` and confirm red.
- [ ] Step 3: Implement the minimal PNG task/result logic.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_png_tasks.py` until green.
- [ ] Step 5: Commit the task.

### Task B6: Full-Report PNG Rendering

**Files:**
- Create: `app/rag/evaluation/poc_runner/reports/png_renderer.py`
- Test: `tests/test_poc_runner_png_report.py`

**Deliverable:**
- PNG rendering covers the full report, not just the heatmap chart.
- Uses the minimal async task path.

- [ ] Step 1: Write failing tests for full-report PNG generation flow.
- [ ] Step 2: Run `pytest -q tests/test_poc_runner_png_report.py` and confirm red.
- [ ] Step 3: Implement the PNG rendering path.
- [ ] Step 4: Re-run `pytest -q tests/test_poc_runner_png_report.py` until green.
- [ ] Step 5: Commit the task.

### Task B7: PNG Export APIs

**Files:**
- Extend: dataset analysis API module
- Test: `tests/test_dataset_analysis_png_api.py`

**Deliverable:**
- Dataset-scoped APIs for:
  - creating PNG export tasks
  - checking PNG task status
  - retrieving the finished PNG result

- [ ] Step 1: Write failing API tests for PNG task creation/status/result.
- [ ] Step 2: Run `pytest -q tests/test_dataset_analysis_png_api.py` and confirm red.
- [ ] Step 3: Implement the PNG APIs.
- [ ] Step 4: Re-run `pytest -q tests/test_dataset_analysis_png_api.py` until green.
- [ ] Step 5: Commit the task.

### Batch B Verification Gate

- [ ] Run the complete Batch B targeted suite.

  ```bash
  pytest -q \
    tests/test_poc_runner_coverage_heatmap.py \
    tests/test_poc_runner_attribution_report.py \
    tests/test_poc_runner_html_report.py \
    tests/test_dataset_analysis_html_api.py \
    tests/test_poc_runner_png_tasks.py \
    tests/test_poc_runner_png_report.py \
    tests/test_dataset_analysis_png_api.py
  ```

- [ ] Re-run any relevant dataset analysis/export API tests from Batch A to confirm no regressions.

- [ ] Update `docs/plans/2026-04-21-backend-plan-execution-roadmap.md` after Batch B is verified.

## Final Completion Checks For This MD

- [ ] Batch A is complete and verified
- [ ] Batch B is complete and verified
- [ ] The master backend roadmap is updated
- [ ] The first source MD is marked complete in the roadmap
- [ ] Remaining deferred items are explicitly listed for future MDs/batches

## Deferred Items From This MD

- [ ] LLM attribution classifier
- [ ] `out_of_scope` control of the live answering path
- [ ] `industry_rules` management API
- [ ] automatic glossary write-back
- [ ] UMAP scatter support
- [ ] any global/tenant-wide analysis dashboards beyond dataset scope
