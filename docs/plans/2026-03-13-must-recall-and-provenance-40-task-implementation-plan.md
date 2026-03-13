# Must-Recall and Provenance 40-Task Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close six backend RAG gaps for open-source quality leadership: deterministic DB must-recall, stronger retrieval contracts, robust multi-table TAG planning, parse-to-recall hard gates, immutable evidence capsules, and CI/runtime closure.

**Architecture:** Keep the existing MimirQ retrieval/TAG pipeline, but add a deterministic “structured-first” path, explicit must-recall contracts, and replayable provenance artifacts. Implement in additive slices with test-first checkpoints, no cross-module rewrites. Each task must be independently verifiable and rollback-safe.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres, SQLite Table Store, existing retrieval orchestrator, pytest, ruff, GitHub Actions, bd issue tracking.

---

## Scope (6 Gaps)

- G1: DB data exists but no strict must-recall guarantee.
- G2: Retrieval contract fallback only covers empty results, not partial-miss critical facts.
- G3: TAG planner remains mostly heuristic for complex multi-table joins.
- G4: Parse quality diagnostics are available but not strict release-gating.
- G5: Citation/trace are strong but still best-effort (not immutable replay capsule).
- G6: CI/runtime closure lacks one-stop pass/fail SLO for must-recall + provenance integrity.

## Task Breakdown (40)

### G1 Deterministic DB Must-Recall Path (Tasks 1-8)

### Task 1: Add must-recall config contract
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 2: Add request-level must-recall schema for retrieval/chat endpoints
**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/api/v1/rag.py`
- Modify: `app/api/v1/chat.py`
- Test: `tests/test_rag_retrieve_endpoints.py`
**Verification:** `pytest -q tests/test_rag_retrieve_endpoints.py`

### Task 3: Add deterministic SQL-first execution mode for dbrows TAG assets
**Files:**
- Modify: `app/services/chat_tag_service.py`
- Modify: `app/services/table_tag_service.py`
- Test: `tests/test_chat_tag_service.py`
**Verification:** `pytest -q tests/test_chat_tag_service.py`

### Task 4: Add mandatory source-key matching for must-recall questions
**Files:**
- Modify: `app/services/chat_tag_service.py`
- Add: `app/rag/policy/must_recall.py`
- Test: `tests/test_tag_must_recall_policy.py`
**Verification:** `pytest -q tests/test_tag_must_recall_policy.py`

### Task 5: Add `must_recall_status` and miss reasons to metrics
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_hardcase_candidate.py`
**Verification:** `pytest -q tests/test_retrieval_hardcase_candidate.py`

### Task 6: Add must-recall summary counters to reports endpoint
**Files:**
- Modify: `app/services/report_service.py`
- Modify: `app/api/v1/reports.py`
- Test: `tests/test_reports_endpoints.py`
**Verification:** `pytest -q tests/test_reports_endpoints.py`

### Task 7: Add deterministic dbrows recall regression fixture
**Files:**
- Add: `ci/retrieval_must_recall_dbrows_fixture.v1.json`
- Add: `tests/test_db_catalog_row_recall.py`
**Verification:** `pytest -q tests/test_db_catalog_row_recall.py`

### Task 8: Document must-recall semantics and operator knobs
**Files:**
- Modify: `docs/guides/table_tag.md`
- Modify: `docs/guides/retrieval_debugging.md`
**Verification:** `ruff check docs/guides/table_tag.md docs/guides/retrieval_debugging.md`

### G2 Retrieval Contract Upgrade for Partial-Miss (Tasks 9-16)

### Task 9: Add new retrieval contract mode `must_recall_strict`
**Files:**
- Modify: `app/rag/retrieval/contract.py`
- Modify: `app/core/config.py`
- Test: `tests/test_retrieval_contract_policy.py`
**Verification:** `pytest -q tests/test_retrieval_contract_policy.py`

### Task 10: Add second-pass retrieval trigger for partial-miss critical signals
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_secondary_pass.py`
**Verification:** `pytest -q tests/test_retrieval_secondary_pass.py`

### Task 11: Add evidence-anchor expectation checks (must-have fields)
**Files:**
- Modify: `app/rag/core/citations.py`
- Add: `app/rag/core/evidence_expectations.py`
- Test: `tests/test_tag_citation_evidence_keys.py`
**Verification:** `pytest -q tests/test_tag_citation_evidence_keys.py`

### Task 12: Add contract-level fail reason taxonomy
**Files:**
- Modify: `app/rag/retrieval/contract.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_contract_fail_reasons.py`
**Verification:** `pytest -q tests/test_retrieval_contract_fail_reasons.py`

### Task 13: Add retrieval trace fields for secondary-pass diff
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/api/v1/rag.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 14: Add query-debug panel payload for contract diagnostics
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_hardcase_candidate.py`
**Verification:** `pytest -q tests/test_retrieval_hardcase_candidate.py`

### Task 15: Add retrieval-only gate metric `must_recall_pass_rate`
**Files:**
- Modify: `app/rag/evaluation/evidence_retrieve_gate.py`
- Modify: `scripts/regression_gate.py`
- Test: `tests/test_regression_gate.py`
**Verification:** `pytest -q tests/test_regression_gate.py`

### Task 16: Document partial-miss fallback contract
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/regression_gate.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/regression_gate.md`

### G3 TAG Planner from Heuristic to Deterministic+Scored (Tasks 17-24)

### Task 17: Add schema graph builder for table-store assets
**Files:**
- Add: `app/services/table_schema_graph.py`
- Modify: `app/services/table_tag_service.py`
- Test: `tests/test_table_tag_join_inference.py`
**Verification:** `pytest -q tests/test_table_tag_join_inference.py`

### Task 18: Add join path scorer with confidence and penalties
**Files:**
- Modify: `app/services/table_tag_service.py`
- Test: `tests/test_table_tag_schema_linking.py`
**Verification:** `pytest -q tests/test_table_tag_schema_linking.py`

### Task 19: Add deterministic plan candidates (top-N) before SQL generation
**Files:**
- Modify: `app/services/table_tag_service.py`
- Test: `tests/test_table_tag_multitable_recall.py`
**Verification:** `pytest -q tests/test_table_tag_multitable_recall.py`

### Task 20: Add strict ambiguity handling for duplicate column semantics
**Files:**
- Modify: `app/services/table_tag_service.py`
- Test: `tests/test_table_tag_ambiguity.py`
**Verification:** `pytest -q tests/test_table_tag_ambiguity.py`

### Task 21: Add planner result contract to dataset tables API
**Files:**
- Modify: `app/api/v1/dataset_tables.py`
- Modify: `app/api/schemas/table_store.py`
- Test: `tests/test_dataset_tables_endpoints.py`
**Verification:** `pytest -q tests/test_dataset_tables_endpoints.py`

### Task 22: Add deterministic SQL rendering fingerprint for TAG plans
**Files:**
- Modify: `app/services/table_tag_service.py`
- Add: `app/services/table_sql_fingerprint.py`
- Test: `tests/test_table_tag_plan_fingerprint.py`
**Verification:** `pytest -q tests/test_table_tag_plan_fingerprint.py`

### Task 23: Add planner-vs-execution mismatch detector
**Files:**
- Modify: `app/services/table_store_service.py`
- Modify: `app/services/chat_tag_service.py`
- Test: `tests/test_table_query_guards.py`
**Verification:** `pytest -q tests/test_table_query_guards.py`

### Task 24: Document deterministic multi-table planning rules
**Files:**
- Modify: `docs/guides/table_tag.md`
**Verification:** `ruff check docs/guides/table_tag.md`

### G4 Parse Quality to Hard Gate (Tasks 25-30)

### Task 25: Add parse-quality gate profile for retrieval runs
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/core/config.py`
- Test: `tests/test_retrieval_parse_quality_gate.py`
**Verification:** `pytest -q tests/test_retrieval_parse_quality_gate.py`

### Task 26: Add parser benchmark strict mode (fail-on-regress)
**Files:**
- Modify: `scripts/parser_benchmark.py`
- Add: `tests/test_parser_benchmark_gate.py`
**Verification:** `pytest -q tests/test_parser_benchmark_gate.py`

### Task 27: Add parse-quality SLO fields in regression run summary
**Files:**
- Modify: `app/rag/evaluation/evidence_retrieve_gate.py`
- Test: `tests/test_regression_run_metrics.py`
**Verification:** `pytest -q tests/test_regression_run_metrics.py`

### Task 28: Add parse-risk candidate auto-enqueue policy
**Files:**
- Modify: `app/services/hardcase_discovery_service.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_hardcase_candidate.py`
**Verification:** `pytest -q tests/test_retrieval_hardcase_candidate.py`

### Task 29: Add CI artifact for parser gate diff
**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/diff_queryset_health_snapshots.py`
- Test: `tests/test_diff_queryset_health_snapshots.py`
**Verification:** `pytest -q tests/test_diff_queryset_health_snapshots.py`

### Task 30: Document parse-quality hard gate playbook
**Files:**
- Modify: `docs/guides/parse_quality_retrieval_diagnostics.md`
- Modify: `docs/guides/parser_benchmark.md`
**Verification:** `ruff check docs/guides/parse_quality_retrieval_diagnostics.md docs/guides/parser_benchmark.md`

### G5 Immutable Evidence Capsule (Tasks 31-36)

### Task 31: Define evidence capsule schema v1
**Files:**
- Add: `app/rag/trace_schema/evidence_capsule.py`
- Modify: `app/api/v1/rag.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 32: Add capsule builder from citations + retrieval config
**Files:**
- Add: `app/rag/core/evidence_capsule_builder.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_evidence_capsule_builder.py`
**Verification:** `pytest -q tests/test_evidence_capsule_builder.py`

### Task 33: Add stable hash fields for replay integrity
**Files:**
- Modify: `app/rag/core/citations.py`
- Modify: `app/rag/core/hashing.py`
- Test: `tests/test_tag_citation_evidence_keys.py`
**Verification:** `pytest -q tests/test_tag_citation_evidence_keys.py`

### Task 34: Add optional persistence endpoint for evidence capsules
**Files:**
- Add: `app/api/v1/evidence_capsules.py`
- Modify: `app/api/v1/__init__.py`
- Test: `tests/test_evidence_capsules_endpoints.py`
**Verification:** `pytest -q tests/test_evidence_capsules_endpoints.py`

### Task 35: Add replay CLI from evidence capsule
**Files:**
- Add: `scripts/replay_from_evidence_capsule.py`
- Test: `tests/test_replay_from_evidence_capsule.py`
**Verification:** `pytest -q tests/test_replay_from_evidence_capsule.py`

### Task 36: Document “有据可查” capsule contract
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Add: `docs/guides/evidence_capsule.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/evidence_capsule.md`

### G6 CI/Runtime Closure and Release Discipline (Tasks 37-40)

### Task 37: Add one-shot must-recall + provenance gate script
**Files:**
- Add: `scripts/must_recall_provenance_gate.py`
- Test: `tests/test_must_recall_provenance_gate.py`
**Verification:** `pytest -q tests/test_must_recall_provenance_gate.py`

### Task 38: Wire gate into CI workflow with artifacts
**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/guides/regression_gate.md`
**Verification:** `pytest -q tests/test_regression_gate.py`

### Task 39: Add release notes template for must-recall/provenance
**Files:**
- Modify: `docs/guides/retrieval_release_notes.md`
- Modify: `CHANGELOG.md`
**Verification:** `ruff check docs/guides/retrieval_release_notes.md`

### Task 40: Add operations runbook and wave status update
**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/waves/status.md`
**Verification:** `ruff check docs/operations.md docs/waves/status.md`

---

## Recommended Execution Order

1. G1 + G2 first (must-recall contract and retrieval behavior).
2. G3 in parallel after G1 baseline lands.
3. G4 + G5 after G2/G3 contracts stabilize.
4. G6 last to freeze CI/release discipline.

## Definition of Done

- `must_recall_pass_rate` is emitted and gated in CI.
- DB row recall supports deterministic SQL-first path with auditable miss reasons.
- TAG multi-table planning has deterministic candidate plans and provenance.
- Parse-quality regressions can fail gate (not only alert).
- Evidence capsule can replay retrieval decisions with stable hash contract.
- `main` branch has passing targeted suites, updated docs, and traceable artifacts.
