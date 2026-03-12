# Top-Tier RAG Gap Wave D Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close six newly identified backend gaps vs top-tier RAG knowledge platforms: index consistency guarantees, strict evidence-default contracts, parse-quality active remediation, stronger TAG/RAG routing separation, sparse channel productionization, and hybrid/ColBERT quality gates.

**Architecture:** Keep the current FastAPI + retrieval orchestrator + connector/TAG architecture; add bounded, additive contracts that make failures observable, recoverable, and gateable in CI. Prioritize deterministic behavior and auditable evidence over feature breadth. Execute in TDD order: schema/contract -> core path -> observability/gate -> docs.

**Tech Stack:** FastAPI, SQLAlchemy, retrieval orchestrator, Table Store (SQLite), pytest, ruff, GitHub Actions, `bd`.

---

## Scope and Priority

- `G1` (P0): Index consistency + drift reconcile (parse/store/index alignment).
- `G2` (P0): Strict evidence contract defaults and grounded-answer controls.
- `G3` (P1): Parse-quality remediation from diagnostics to active actions.
- `G4` (P1): TAG sidecar routing hard separation to reduce retrieval noise.
- `G5` (P1): Sparse channel productionization and provider-level gates.
- `G6` (P1): Hybrid + ColBERT bounded gates and release integration.

## 40 Tasks

### G1 Index Consistency and Reconcile (Tasks 1-8)

### Task 1: Add index consistency feature flags and strictness levels
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 2: Add index operation result contract schema (vector/bm25/kg)
**Files:**
- Modify: `app/api/schemas/document.py`
- Modify: `app/api/v1/documents.py`
- Test: `tests/test_documents_chunk_operations.py`
**Verification:** `pytest -q tests/test_documents_chunk_operations.py`

### Task 3: Implement patch-chunk strict mode with drift marker emission
**Files:**
- Modify: `app/api/v1/documents.py`
- Add/Modify: `app/services/index_audit_service.py`
- Test: `tests/test_documents_chunk_patch_consistency.py`
**Verification:** `pytest -q tests/test_documents_chunk_patch_consistency.py`

### Task 4: Implement delete/disable chunk strict mode + reconcile queueing
**Files:**
- Modify: `app/api/v1/documents.py`
- Modify: `app/services/index_audit_service.py`
- Test: `tests/test_documents_chunk_disable_delete_consistency.py`
**Verification:** `pytest -q tests/test_documents_chunk_disable_delete_consistency.py`

### Task 5: Add index drift entity/store for unresolved ops
**Files:**
- Modify/Add: `app/models/*index*`
- Modify/Add: `app/services/index_audit_service.py`
- Test: `tests/test_index_audit_service.py`
**Verification:** `pytest -q tests/test_index_audit_service.py`

### Task 6: Add bounded index-drift replay CLI
**Files:**
- Add: `scripts/replay_index_drift.py`
- Test: `tests/test_replay_index_drift.py`
**Verification:** `pytest -q tests/test_replay_index_drift.py`

### Task 7: Add API endpoint to list/resolve index drift items
**Files:**
- Modify: `app/api/v1/observability.py`
- Modify: `app/api/schemas/observability.py`
- Test: `tests/test_observability_index_drift_endpoint.py`
**Verification:** `pytest -q tests/test_observability_index_drift_endpoint.py`

### Task 8: Document index consistency modes + recovery runbook
**Files:**
- Modify: `docs/guides/observability_dashboard.md`
- Modify: `docs/guides/retrieval_debugging.md`
**Verification:** `ruff check docs/guides/observability_dashboard.md docs/guides/retrieval_debugging.md`

### G2 Strict Evidence Contract Defaults (Tasks 9-15)

### Task 9: Add grounded_strict retrieval profile contract
**Files:**
- Modify: `app/rag/core/retrieval_profiles.py`
- Test: `tests/test_retrieval_profile_schema.py`
**Verification:** `pytest -q tests/test_retrieval_profile_schema.py`

### Task 10: Extend ChatRAGConfig profile projection to retrieval-contract fields
**Files:**
- Modify: `app/api/schemas/chat.py`
- Test: `tests/test_chat_default_retrieval_profile.py`
**Verification:** `pytest -q tests/test_chat_default_retrieval_profile.py`

### Task 11: Add retrieval profile metadata to retrieval-profiles endpoint
**Files:**
- Modify: `app/api/v1/retrieval_profiles.py`
- Test: `tests/test_retrieval_profiles_endpoint.py`
**Verification:** `pytest -q tests/test_retrieval_profiles_endpoint.py`

### Task 12: Add dataset-level strict grounding default mapping
**Files:**
- Modify: `app/services/rag_defaults.py`
- Modify: `app/api/schemas/dataset.py`
- Test: `tests/test_dataset_rag_defaults.py`
**Verification:** `pytest -q tests/test_dataset_rag_defaults.py`

### Task 13: Add strict-evidence regression cases (span-required + refusal semantics)
**Files:**
- Add: `tests/test_retrieval_contract_strict_evidence.py`
**Verification:** `pytest -q tests/test_retrieval_contract_strict_evidence.py`

### Task 14: Add bounded CI check for strict-evidence profile
**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

### Task 15: Document grounded_strict profile rollout guidance
**Files:**
- Modify: `docs/guides/rag_optimization.md`
- Modify: `docs/guides/retrieval_debugging.md`
**Verification:** `ruff check docs/guides/rag_optimization.md docs/guides/retrieval_debugging.md`

### G3 Parse Quality Active Remediation (Tasks 16-22)

### Task 16: Add parse-quality remediation policy settings
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 17: Add parse-risk classification helper in retrieval path
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_parse_quality_signals.py`
**Verification:** `pytest -q tests/test_retrieval_parse_quality_signals.py`

### Task 18: Add optional automatic hardcase emission for parse risk
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/services/hardcase_discovery_service.py`
- Test: `tests/test_retrieval_parse_quality_hardcase_emit.py`
**Verification:** `pytest -q tests/test_retrieval_parse_quality_hardcase_emit.py`

### Task 19: Add dataset parse-risk summary aggregation in reports
**Files:**
- Modify: `app/services/report_service.py`
- Test: `tests/test_report_service_parse_quality.py`
**Verification:** `pytest -q tests/test_report_service_parse_quality.py`

### Task 20: Add remediation CLI (reparse candidate list from parse-risk summary)
**Files:**
- Add: `scripts/plan_parse_quality_reparse.py`
- Test: `tests/test_plan_parse_quality_reparse.py`
**Verification:** `pytest -q tests/test_plan_parse_quality_reparse.py`

### Task 21: Add CI artifact for parse-risk tail in queryset health report
**Files:**
- Modify: `scripts/diff_queryset_health_snapshots.py`
- Test: `tests/test_diff_queryset_health_snapshots.py`
**Verification:** `pytest -q tests/test_diff_queryset_health_snapshots.py`

### Task 22: Document parse-quality remediation playbook
**Files:**
- Modify: `docs/guides/parse_quality_retrieval_diagnostics.md`
**Verification:** `ruff check docs/guides/parse_quality_retrieval_diagnostics.md`

### G4 TAG/RAG Routing Separation (Tasks 23-28)

### Task 23: Add explicit table-sidecar exclusive routing switch
**Files:**
- Modify: `app/core/config.py`
- Modify: `app/api/schemas/document.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 24: Skip vector/BM25 ingestion for parser-emitted table segments when exclusive mode on
**Files:**
- Modify: `app/services/indexer.py`
- Modify: `app/api/v1/documents.py`
- Test: `tests/test_table_store_routing.py`
**Verification:** `pytest -q tests/test_table_store_routing.py`

### Task 25: Add metadata contract to mark table-routed chunks and exclusion reason
**Files:**
- Modify: `app/api/v1/documents.py`
- Test: `tests/test_documents_pipeline_version_diff.py`
**Verification:** `pytest -q tests/test_documents_pipeline_version_diff.py`

### Task 26: Add retrieval regression to ensure table-noise does not dominate text answers
**Files:**
- Add: `tests/test_table_noise_recall_regression.py`
**Verification:** `pytest -q tests/test_table_noise_recall_regression.py`

### Task 27: Add dataset table-routing policy endpoint fields for audit
**Files:**
- Modify: `app/api/v1/datasets.py`
- Modify: `app/api/schemas/dataset.py`
- Test: `tests/test_datasets_profile_endpoints.py`
**Verification:** `pytest -q tests/test_datasets_profile_endpoints.py`

### Task 28: Document TAG/RAG exclusive routing semantics and migration notes
**Files:**
- Modify: `docs/guides/table_tag.md`
- Modify: `docs/guides/chunking_playbook.md`
**Verification:** `ruff check docs/guides/table_tag.md docs/guides/chunking_playbook.md`

### G5 Sparse Channel Productionization (Tasks 29-34)

### Task 29: Add sparse provider capability contract and validation
**Files:**
- Modify: `app/rag/retrieval/sparse.py`
- Modify: `app/core/config.py`
- Test: `tests/test_sparse_retrieval.py`
**Verification:** `pytest -q tests/test_sparse_retrieval.py`

### Task 30: Add sparse provider status debug payload in retrieval trace
**Files:**
- Modify: `app/rag/retriever.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 31: Add sparse provider fallback reason taxonomy in metrics
**Files:**
- Modify: `app/rag/retrieval/sparse_prometheus_metrics.py`
- Test: `tests/test_sparse_prometheus_metrics.py`
**Verification:** `pytest -q tests/test_sparse_prometheus_metrics.py`

### Task 32: Add bounded sparse ablation slice in nightly runner
**Files:**
- Modify: `scripts/run_nightly_ablations.py`
- Test: `tests/test_run_nightly_ablations.py`
**Verification:** `pytest -q tests/test_run_nightly_ablations.py`

### Task 33: Add sparse retrieval CI contract test (provider metadata + artifact)
**Files:**
- Modify: `.github/workflows/ci.yml`
- Add: `tests/test_ci_sparse_channel_artifact.py`
**Verification:** `pytest -q tests/test_ci_sparse_channel_artifact.py`

### Task 34: Document sparse production rollout and rollback policy
**Files:**
- Modify: `docs/guides/sparse_retrieval.md`
**Verification:** `ruff check docs/guides/sparse_retrieval.md`

### G6 Hybrid + ColBERT Bounded Gates (Tasks 35-40)

### Task 35: Add hybrid bounded retrieval fixture and baseline snapshot
**Files:**
- Add: `data/sample/retrieval_fixture_hybrid_v1.json`
- Add: `ci/queryset_health_snapshot_hybrid_baseline.v1.json`
- Test: `tests/test_run_queryset_health_diagnostics.py`
**Verification:** `pytest -q tests/test_run_queryset_health_diagnostics.py`

### Task 36: Extend retrieval-only-bounded-gate workflow with hybrid run + diff artifacts
**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

### Task 37: Add hybrid workflow artifact contract tests
**Files:**
- Add: `tests/test_ci_hybrid_query_health_artifact.py`
**Verification:** `pytest -q tests/test_ci_hybrid_query_health_artifact.py`

### Task 38: Add ColBERT retrieval bounded regression fixture and tests
**Files:**
- Add: `tests/test_colbert_retrieval_regression.py`
- Modify: `tests/test_retrieval_ablation.py`
**Verification:** `pytest -q tests/test_colbert_retrieval_regression.py tests/test_retrieval_ablation.py`

### Task 39: Add release gate support for hybrid bounded queryset artifact input
**Files:**
- Modify: `scripts/release_gate.py`
- Modify: `docs/guides/release_gate.md`
- Test: `tests/test_retrieval_regression_slo_gate.py`
**Verification:** `pytest -q tests/test_retrieval_regression_slo_gate.py`

### Task 40: Document hybrid+colbert gate interpretation and rollout criteria
**Files:**
- Modify: `docs/guides/retrieval_release_notes.md`
- Modify: `docs/guides/colbert_ann_retrieval.md`
**Verification:** `ruff check docs/guides/retrieval_release_notes.md docs/guides/colbert_ann_retrieval.md`

## Batch Execution Order

1. Batch A: Tasks 35-37 (hybrid CI bounded gate visibility).
2. Batch B: Tasks 9-15 (strict evidence contracts).
3. Batch C: Tasks 1-8 (index consistency and drift reconcile).
4. Batch D: Tasks 23-28 (TAG/RAG routing separation).
5. Batch E: Tasks 16-22 (parse-quality active remediation).
6. Batch F: Tasks 29-34 + 38-40 (sparse/colbert productionization + release gate).

## Global Quality Gates

- `ruff check app scripts tests docs/guides`
- Batch-specific `pytest -q` suites listed per task
- End-to-end regression subset after each batch:
  - `pytest -q tests/test_claim_check.py tests/test_retrieval_profile_schema.py tests/test_ci_retrieval_only_bounded_gate_workflow.py tests/test_retrieval_regression_slo_gate.py`
