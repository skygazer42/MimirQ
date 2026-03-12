# Top-Tier RAG Gap Wave C Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining top-tier backend RAG gaps after Wave B: DB row-level recall, multi-table TAG recall, stronger incremental freshness, higher-fidelity claim verification explainability, feedback-to-online automation, CI drift artifacts, and docs/runtime contract consistency.

**Architecture:** Keep existing retrieval/connector/TAG architecture, extend it in bounded additive slices, and prioritize deterministic behavior with auditable diagnostics. Implement in TDD order: contract/schema first, then execution path, then metrics/trace/citations, then docs. Avoid cross-cutting rewrites; each task must be independently testable and rollback-safe.

**Tech Stack:** FastAPI, SQLAlchemy, existing connector runners, Table Store (SQLite), retrieval orchestrator/engine/langgraph, pytest, ruff, GitHub Actions.

---

## Scope and Priority

- `G1` (P0): DB row-level recall and evidence grounding.
- `G2` (P0): Multi-table TAG planning and recall coverage.
- `G3` (P1): Incremental freshness correctness for crawl-like sources.
- `G4` (P1): Claim verifier fidelity + per-claim explainability.
- `G5` (P1): Feedback -> train -> gate -> canary automation.
- `G6` (P2): CI drift artifacts and quality gates.
- `G7` (P2): Docs/runtime contract consistency.

## 40 Tasks

### G1 DB Row-Level Recall (Tasks 1-8)

### Task 1: Add DB row-ingest feature flags and validation
**Files:**  
- Modify: `app/core/config.py`  
- Test: `tests/test_settings_retrieval_validation.py`  
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 2: Extend connector config schemas for row-sync controls
**Files:**  
- Modify: `app/api/schemas/connector.py`  
- Modify: `app/api/v1/connectors.py`  
- Test: `tests/test_connectors_endpoints.py`  
**Verification:** `pytest -q tests/test_connectors_endpoints.py`

### Task 3: Add row-snapshot extraction helper for mysql/sqlserver catalog connectors
**Files:**  
- Modify: `app/api/v1/connectors.py`  
- Add/Modify: `app/services/*catalog*` (existing DB catalog helpers)  
- Test: `tests/test_connector_sync_state.py`  
**Verification:** `pytest -q tests/test_connector_sync_state.py`

### Task 4: Persist row snapshots into Table Store sidecar with bounded caps
**Files:**  
- Modify: `app/services/table_store_service.py`  
- Modify: `app/api/v1/connectors.py`  
- Test: `tests/test_table_store_service.py` (or nearest existing suite)  
**Verification:** `pytest -q tests/test_table_store_service.py`

### Task 5: Add row-level source metadata contract (table, pk/hash, sync token)
**Files:**  
- Modify: `app/api/v1/connectors.py`  
- Modify: `app/rag/core/citations.py`  
- Test: `tests/test_tag_citation_evidence_keys.py`  
**Verification:** `pytest -q tests/test_tag_citation_evidence_keys.py`

### Task 6: Route DB row-backed table assets into chat TAG selection path
**Files:**  
- Modify: `app/services/chat_tag_service.py`  
- Test: `tests/test_chat_tag_service.py`  
**Verification:** `pytest -q tests/test_chat_tag_service.py`

### Task 7: Add integration tests for DB row recall determinism
**Files:**  
- Add: `tests/test_db_catalog_row_recall.py`  
- Modify: `tests/test_dataset_tables_endpoints.py`  
**Verification:** `pytest -q tests/test_db_catalog_row_recall.py tests/test_dataset_tables_endpoints.py`

### Task 8: Document DB row-level recall semantics and limits
**Files:**  
- Modify: `docs/guides/connectors.md`  
- Modify: `docs/guides/table_tag.md`  
**Verification:** `ruff check docs/guides/connectors.md docs/guides/table_tag.md`

### G2 Multi-Table TAG Coverage (Tasks 9-16)

### Task 9: Extend deterministic planner to emit bounded JOIN plans
**Files:**  
- Modify: `app/services/table_tag_service.py`  
- Test: `tests/test_table_tag_schema_linking.py`  
**Verification:** `pytest -q tests/test_table_tag_schema_linking.py`

### Task 10: Add schema relationship inference helper (key overlap/PK heuristics)
**Files:**  
- Modify: `app/services/table_tag_service.py`  
- Add: `tests/test_table_tag_join_inference.py`  
**Verification:** `pytest -q tests/test_table_tag_join_inference.py`

### Task 11: Add join-safe SQL validator constraints for TAG
**Files:**  
- Modify: `app/services/table_store_service.py`  
- Test: `tests/test_table_query_guardrails.py`  
**Verification:** `pytest -q tests/test_table_query_guardrails.py`

### Task 12: Add multi-table candidate assembly in chat TAG bridge
**Files:**  
- Modify: `app/services/chat_tag_service.py`  
- Test: `tests/test_chat_tag_service.py`  
**Verification:** `pytest -q tests/test_chat_tag_service.py`

### Task 13: Add dynamic table-pick policy by query complexity and schema-link score
**Files:**  
- Modify: `app/services/chat_tag_service.py`  
- Test: `tests/test_chat_tag_service.py`  
**Verification:** `pytest -q tests/test_chat_tag_service.py`

### Task 14: Surface join provenance in TAG payload and citations
**Files:**  
- Modify: `app/services/chat_tag_service.py`  
- Modify: `app/rag/core/citations.py`  
- Test: `tests/test_tag_citation_evidence_keys.py`  
**Verification:** `pytest -q tests/test_tag_citation_evidence_keys.py`

### Task 15: Add dataset table ask API support for multi-table explain metadata
**Files:**  
- Modify: `app/api/v1/dataset_tables.py`  
- Modify: `app/api/schemas/table_store.py`  
- Test: `tests/test_dataset_tables_endpoints.py`  
**Verification:** `pytest -q tests/test_dataset_tables_endpoints.py`

### Task 16: Add multi-table TAG regression suite and docs
**Files:**  
- Add: `tests/test_table_tag_multitable_recall.py`  
- Modify: `docs/guides/table_tag.md`  
**Verification:** `pytest -q tests/test_table_tag_multitable_recall.py`

### G3 Incremental Freshness Correctness (Tasks 17-22)

### Task 17: Add content-fingerprint helper for web crawl pages
**Files:**  
- Modify: `app/services/web_crawler.py`  
- Modify: `app/api/v1/connectors.py`  
- Test: `tests/test_web_crawl_delta_sync.py`  
**Verification:** `pytest -q tests/test_web_crawl_delta_sync.py`

### Task 18: Switch web_crawl source manifest token from URL-hash to content-aware token
**Files:**  
- Modify: `app/api/v1/connectors.py`  
- Test: `tests/test_connector_saved_state_resume.py`  
**Verification:** `pytest -q tests/test_connector_saved_state_resume.py`

### Task 19: Add fallback token strategy (etag/last-modified/body-hash precedence)
**Files:**  
- Modify: `app/api/v1/connectors.py`  
- Test: `tests/test_connector_sync_state.py`  
**Verification:** `pytest -q tests/test_connector_sync_state.py`

### Task 20: Add changed-content-same-url incremental replay logic
**Files:**  
- Modify: `app/api/v1/connectors.py`  
- Test: `tests/test_web_crawl_delta_sync.py`  
**Verification:** `pytest -q tests/test_web_crawl_delta_sync.py`

### Task 21: Add removed-url reconcile parity tests for crawl connector
**Files:**  
- Modify: `tests/test_connector_saved_state_resume.py`  
- Add: `tests/test_web_crawl_removed_reconcile.py`  
**Verification:** `pytest -q tests/test_connector_saved_state_resume.py tests/test_web_crawl_removed_reconcile.py`

### Task 22: Document web_crawl/drive/minio incremental semantics with examples
**Files:**  
- Modify: `docs/guides/connectors.md`  
**Verification:** `ruff check docs/guides/connectors.md`

### G4 Claim Verifier Fidelity + Explainability (Tasks 23-28)

### Task 23: Extend claim verifier diagnostics schema (reason_code, contradiction_type)
**Files:**  
- Modify: `app/rag/core/claim_verifier.py`  
- Test: `tests/test_claim_verifier.py`  
**Verification:** `pytest -q tests/test_claim_verifier.py`

### Task 24: Export per-claim removal reasons into claim_check metrics payload
**Files:**  
- Modify: `app/rag/engine.py`  
- Modify: `app/rag/pipelines/langgraph.py`  
- Test: `tests/test_claim_check.py`  
**Verification:** `pytest -q tests/test_claim_check.py`

### Task 25: Add optional NLI verifier provider contract (bounded, off by default)
**Files:**  
- Modify: `app/core/config.py`  
- Add: `app/rag/core/claim_nli_verifier.py`  
- Test: `tests/test_settings_retrieval_validation.py`  
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 26: Wire NLI verifier fallback chain into text/structured claim checking
**Files:**  
- Modify: `app/rag/core/text.py`  
- Modify: `app/rag/core/claim_evidence.py`  
- Test: `tests/test_claim_verifier.py`  
**Verification:** `pytest -q tests/test_claim_verifier.py`

### Task 27: Add contradiction edge-case regression set (numeric range, temporal negation)
**Files:**  
- Add: `tests/test_claim_verifier_contradictions.py`  
**Verification:** `pytest -q tests/test_claim_verifier_contradictions.py`

### Task 28: Document claim verifier modes and diagnostics interpretation
**Files:**  
- Modify: `docs/guides/retrieval_debugging.md`  
- Modify: `docs/guides/rag_optimization.md`  
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/rag_optimization.md`

### G5 Feedback -> Online Automation (Tasks 29-34)

### Task 29: Build hard-negative mining job from traces and feedback events
**Files:**  
- Modify/Add: `scripts/train_ltr_from_regression_cases.py`  
- Modify/Add: `app/services/*ltr*`  
- Test: `tests/test_ltr_hard_negative_mining.py`  
**Verification:** `pytest -q tests/test_ltr_hard_negative_mining.py`

### Task 30: Add rollout gate policy profile schema (pass/warn/block + canary ratio)
**Files:**  
- Modify: `app/services/ltr_rollout_workflow.py`  
- Test: `tests/test_ltr_rollout_workflow.py`  
**Verification:** `pytest -q tests/test_ltr_rollout_workflow.py`

### Task 31: Add canary activation CLI flow after gate pass
**Files:**  
- Modify: `scripts/ltr_rollout_gate.py`  
- Modify: `scripts/prepare_ltr_rollout.py`  
- Test: `tests/test_ltr_rollout_gate.py`  
**Verification:** `pytest -q tests/test_ltr_rollout_gate.py`

### Task 32: Add adaptive routing online reward writeback schema
**Files:**  
- Modify: `app/services/rag_config_template_resolver.py`  
- Modify: `app/api/v1/chat.py`  
- Test: `tests/test_rag_config_template_adaptive_routing.py`  
**Verification:** `pytest -q tests/test_rag_config_template_adaptive_routing.py`

### Task 33: Add rollback trigger helper based on online degradation windows
**Files:**  
- Modify: `app/services/ltr_model_registry.py`  
- Add: `tests/test_ltr_registry_rollback_policy.py`  
**Verification:** `pytest -q tests/test_ltr_registry_rollback_policy.py`

### Task 34: Update feedback->train->gate->activate runbook with canary/rollback
**Files:**  
- Modify: `docs/guides/reranking_ltr.md`  
**Verification:** `ruff check docs/guides/reranking_ltr.md`

### G6 CI Drift Artifacts and Gates (Tasks 35-38)

### Task 35: Implement queryset health diff markdown artifact in CI (MimirQ-80yl)
**Files:**  
- Modify: `.github/workflows/*` (bounded-gate/retrieval quality workflow)  
- Reuse: `scripts/diff_queryset_health_snapshots.py`  
- Test: `tests/test_ci_query_health_artifact.py`  
**Verification:** `pytest -q tests/test_ci_query_health_artifact.py`

### Task 36: Add policy/hash drift summary section to CI artifact template
**Files:**  
- Modify: `scripts/diff_queryset_health_snapshots.py`  
- Test: `tests/test_queryset_health_diff.py`  
**Verification:** `pytest -q tests/test_queryset_health_diff.py`

### Task 37: Add retrieval contract + claim verifier benchmark slice in gate job
**Files:**  
- Modify: CI workflow + regression gate config under `scripts/`/`docs/guides`  
- Test: `tests/test_claim_check.py` + `tests/test_retrieval_contract_policy.py` in CI matrix  
**Verification:** `pytest -q tests/test_claim_check.py tests/test_retrieval_contract_policy.py`

### Task 38: Add explicit CI failure thresholds for drift classes
**Files:**  
- Modify: `docs/guides/release_gate.md`  
- Modify: CI workflow env/args  
**Verification:** `ruff check docs/guides/release_gate.md`

### G7 Docs and Contract Consistency (Tasks 39-40)

### Task 39: Reconcile connectors guide with runtime capability matrix
**Files:**  
- Modify: `docs/guides/connectors.md`  
- Cross-check: `app/services/connector_registry.py`  
**Verification:** `rg -n \"supports_incremental|supports_resume\" docs/guides/connectors.md app/services/connector_registry.py`

### Task 40: Replace broken retrieval-only gap snapshot reference with live source
**Files:**  
- Modify: `docs/guides/reranking_ltr.md`  
- Optionally add: `docs/plans/2026-03-12-retrieval-only-gap-snapshot.md`  
**Verification:** `rg -n \"retrieval-only-rag-gap-snapshot\" docs -g'*.md'`

## Batch Execution Order

1. Batch A: Tasks 39-40, 35-36 (quick consistency and CI visibility).  
2. Batch B: Tasks 17-22 (freshness correctness).  
3. Batch C: Tasks 9-16 (multi-table TAG coverage).  
4. Batch D: Tasks 1-8 (DB row-level recall).  
5. Batch E: Tasks 23-28 (claim verifier fidelity).  
6. Batch F: Tasks 29-34, 37-38 (automation and gates).

## Global Quality Gates (Run after each batch)

- `ruff check app scripts tests docs/guides`
- Focused `pytest -q` on batch-specific suites
- End-to-end regression subset:
  - `pytest -q tests/test_claim_check.py tests/test_chat_tag_service.py tests/test_dataset_tables_endpoints.py tests/test_connectors_endpoints.py tests/test_ltr_rollout_gate.py`

