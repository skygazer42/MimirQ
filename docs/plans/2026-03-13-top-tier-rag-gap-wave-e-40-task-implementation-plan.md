# Top-Tier RAG Gap Closure (Wave E) 40-Task Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining backend gaps after Wave23 with stronger evidence integrity, automatic must-recall enforcement, higher-confidence TAG planning, adaptive retrieval routing, stricter parse/answer gates, KG query-mode routing, and contextual retrieval boosts.

**Architecture:** Reuse existing MimirQ retrieval + KG + TAG + CI pipeline. Add deterministic integrity checks and low-cardinality policy layers first, then expand runtime quality gates and diagnostics. No GraphRAG framework dependency is introduced; all KG improvements are built on the existing `app/rag/kg/*` modules.

**Tech Stack:** FastAPI, SQLAlchemy, Python services/scripts, existing KG pipeline, pytest, ruff, GitHub Actions.

---

## Scope and Constraints

- Must not introduce GraphRAG package/framework.
- Must keep KG capabilities on top of existing `kg_search` / `RecallSearcher` / rerank stack.
- Must preserve deterministic CI behavior for merge gates.
- Must keep new diagnostics bounded and PII-safe.

---

## G1 — Evidence Capsule Integrity Hardening (Tasks 1-5)

### Task 1: Add evidence integrity/signing config knobs
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 2: Add stable HMAC helpers for capsule signing
**Files:**
- Modify: `app/rag/core/hashing.py`
- Test: `tests/test_evidence_capsule_builder.py`
**Verification:** `pytest -q tests/test_evidence_capsule_builder.py`

### Task 3: Enforce strict capsule validation (hash recompute + citation/anchor checks + signature)
**Files:**
- Modify: `app/rag/core/evidence_capsule_builder.py`
- Modify: `app/rag/core/citations.py`
- Test: `tests/test_evidence_capsule_builder.py`
**Verification:** `pytest -q tests/test_evidence_capsule_builder.py`

### Task 4: Make capsule persistence fail-closed for tampered payloads
**Files:**
- Modify: `app/api/v1/evidence_capsules.py`
- Test: `tests/test_evidence_capsules_endpoints.py`
**Verification:** `pytest -q tests/test_evidence_capsules_endpoints.py`

### Task 5: Upgrade replay + gate to strict integrity checks
**Files:**
- Modify: `scripts/replay_from_evidence_capsule.py`
- Modify: `scripts/must_recall_provenance_gate.py`
- Test: `tests/test_replay_from_evidence_capsule.py`
- Test: `tests/test_must_recall_provenance_gate.py`
**Verification:** `pytest -q tests/test_replay_from_evidence_capsule.py tests/test_must_recall_provenance_gate.py`

---

## G2 — Must-Recall Auto Enforcement (Tasks 6-10)

### Task 6: Add auto must-recall inference settings
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 7: Add source-key inference policy module
**Files:**
- Add: `app/rag/policy/must_recall_auto.py`
- Test: `tests/test_tag_must_recall_policy.py`
**Verification:** `pytest -q tests/test_tag_must_recall_policy.py`

### Task 8: Integrate auto source-key inference into retrieval orchestrator
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_contract_fail_reasons.py`
**Verification:** `pytest -q tests/test_retrieval_contract_fail_reasons.py`

### Task 9: Emit explicit auto-inference diagnostics and metric fields
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/services/report_service.py`
- Test: `tests/test_reports_endpoints.py`
**Verification:** `pytest -q tests/test_reports_endpoints.py`

### Task 10: Document auto must-recall behavior and operator knobs
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/table_tag.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/table_tag.md`

---

## G3 — TAG Planner Cost Model Upgrade (Tasks 11-15)

### Task 11: Add TAG planner cost model settings
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 12: Extend schema graph scoring with fanout/selectivity penalties
**Files:**
- Modify: `app/services/table_schema_graph.py`
- Test: `tests/test_table_schema_graph.py`
**Verification:** `pytest -q tests/test_table_schema_graph.py`

### Task 13: Pass row_count/sample stats into join candidate planning
**Files:**
- Modify: `app/services/table_tag_service.py`
- Test: `tests/test_table_tag_schema_linking.py`
**Verification:** `pytest -q tests/test_table_tag_schema_linking.py`

### Task 14: Add planner low-confidence contract and fail reason
**Files:**
- Modify: `app/services/table_tag_service.py`
- Modify: `app/services/chat_tag_service.py`
- Test: `tests/test_table_tag_ambiguity.py`
**Verification:** `pytest -q tests/test_table_tag_ambiguity.py`

### Task 15: Update TAG planner docs for cost-model signals
**Files:**
- Modify: `docs/guides/table_tag.md`
**Verification:** `ruff check docs/guides/table_tag.md`

---

## G4 — Adaptive Retrieval Routing (Tasks 16-20)

### Task 16: Add adaptive router policy schema and loader
**Files:**
- Modify: `app/rag/policy/intent_router.py`
- Test: `tests/test_intent_router.py`
**Verification:** `pytest -q tests/test_intent_router.py`

### Task 17: Add adaptive overrides in retrieval routing stage
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 18: Add policy generator script from regression run artifacts
**Files:**
- Add: `scripts/generate_adaptive_router_policy.py`
- Test: `tests/test_generate_adaptive_router_policy.py`
**Verification:** `pytest -q tests/test_generate_adaptive_router_policy.py`

### Task 19: Add CI artifact generation for adaptive router policy
**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

### Task 20: Document adaptive router rollout and rollback policy
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/retrieval_ablation.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/retrieval_ablation.md`

---

## G5 — Parse Gate Tightening (Tasks 21-25)

### Task 21: Add parser strict profile config artifact
**Files:**
- Add: `ci/parser_strict_profile.v1.json`
- Test: `tests/test_parser_benchmark_gate.py`
**Verification:** `pytest -q tests/test_parser_benchmark_gate.py`

### Task 22: Add parser benchmark support for strict profile input
**Files:**
- Modify: `scripts/parser_benchmark.py`
- Test: `tests/test_parser_benchmark_gate.py`
**Verification:** `pytest -q tests/test_parser_benchmark_gate.py`

### Task 23: Expand CI parser gate to use strict profile contract
**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

### Task 24: Add parser regression severity summary artifact
**Files:**
- Modify: `scripts/parser_benchmark.py`
- Test: `tests/test_parser_benchmark_gate.py`
**Verification:** `pytest -q tests/test_parser_benchmark_gate.py`

### Task 25: Update parser gate runbook
**Files:**
- Modify: `docs/guides/parser_benchmark.md`
- Modify: `docs/guides/parse_quality_retrieval_diagnostics.md`
**Verification:** `ruff check docs/guides/parser_benchmark.md docs/guides/parse_quality_retrieval_diagnostics.md`

---

## G6 — Answer-Level Gate Hardening (Tasks 26-30)

### Task 26: Add deterministic answer-quality gate script
**Files:**
- Add: `scripts/answer_quality_gate.py`
- Test: `tests/test_answer_quality_gate.py`
**Verification:** `pytest -q tests/test_answer_quality_gate.py`

### Task 27: Add summary extraction helpers for answer-quality gate
**Files:**
- Modify: `app/rag/evaluation/ragas.py`
- Test: `tests/test_regression_gate.py`
**Verification:** `pytest -q tests/test_regression_gate.py`

### Task 28: Wire answer-quality gate into regression CI path
**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

### Task 29: Add answer-quality threshold policy artifact
**Files:**
- Add: `ci/answer_quality_thresholds.v1.json`
- Test: `tests/test_answer_quality_gate.py`
**Verification:** `pytest -q tests/test_answer_quality_gate.py`

### Task 30: Document answer-level gate semantics
**Files:**
- Modify: `docs/guides/evaluation_maturity_model.md`
- Modify: `docs/guides/regression_gate.md`
**Verification:** `ruff check docs/guides/evaluation_maturity_model.md docs/guides/regression_gate.md`

---

## G7 — KG Query-Mode Routing (No GraphRAG Dependency) (Tasks 31-35)

### Task 31: Add KG query-mode classifier (`local|global|drift`)
**Files:**
- Add: `app/rag/kg/search/query_mode.py`
- Test: `tests/test_kg_query_mode.py`
**Verification:** `pytest -q tests/test_kg_query_mode.py`

### Task 32: Extend KG search config with query_mode fields
**Files:**
- Modify: `app/rag/kg/search/config.py`
- Test: `tests/test_kg_query_mode.py`
**Verification:** `pytest -q tests/test_kg_query_mode.py`

### Task 33: Route KG search mode in pipeline facade
**Files:**
- Modify: `app/rag/kg/pipeline.py`
- Test: `tests/test_kg_search_cache.py`
**Verification:** `pytest -q tests/test_kg_search_cache.py`

### Task 34: Add mode-aware recall/rerank parameter shaping
**Files:**
- Modify: `app/rag/kg/search/recall.py`
- Test: `tests/test_kg_search_diagnostics.py`
**Verification:** `pytest -q tests/test_kg_search_diagnostics.py`

### Task 35: Document KG query-mode guidance
**Files:**
- Modify: `docs/guides/knowledge_graph.md`
- Modify: `docs/guides/retrieval_debugging.md`
**Verification:** `ruff check docs/guides/knowledge_graph.md docs/guides/retrieval_debugging.md`

---

## G8 — Contextual Retrieval Boost (Tasks 36-40)

### Task 36: Add contextual follow-up query builder from retrieved docs
**Files:**
- Add: `app/rag/retrieval/contextual_followup.py`
- Test: `tests/test_contextual_followup.py`
**Verification:** `pytest -q tests/test_contextual_followup.py`

### Task 37: Add retrieval settings for contextual follow-up pass
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 38: Integrate contextual follow-up retrieval pass in orchestrator
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_secondary_pass.py`
**Verification:** `pytest -q tests/test_retrieval_secondary_pass.py`

### Task 39: Emit contextual follow-up diagnostics in trace/metrics
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 40: Update retrieval debugging docs with contextual mode playbook
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/retrieval_release_notes.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/retrieval_release_notes.md`

