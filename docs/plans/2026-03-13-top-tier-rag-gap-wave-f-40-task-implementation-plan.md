# Top-Tier RAG Gap Closure (Wave F) 40-Task Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining backend gaps versus top-tier RAG systems after Wave E, focusing on provable recall coverage, stronger learned routing/planning, iterative retrieval reasoning, productionized ranking channels, and automated quality-ops loops.

**Architecture:** Reuse existing MimirQ retrieval/KG/TAG stack and extend it with deterministic contracts plus optional learned components under strict fail-safe gates. Do not introduce GraphRAG framework dependencies; all graph functionality stays inside current `app/rag/kg/*` modules. Prioritize auditable traceability and bounded CI artifacts.

**Tech Stack:** FastAPI, Python services/scripts, existing KG/TAG modules, pytest, ruff, GitHub Actions.

---

## Scope and Constraints

- Must not introduce GraphRAG package/framework.
- Reuse existing KG (`kg_search`, `RecallSearcher`, rerankers) and TAG pipeline.
- Keep deterministic fallback path for every learned component.
- Keep diagnostics PII-safe and low-cardinality.

---

## G1 — Provable Must-Recall Coverage (Tasks 1-5)

### Task 1: Add retrieval obligation ledger schema for source-key coverage proof
**Files:**
- Add: `app/rag/policy/recall_obligation.py`
- Test: `tests/test_recall_obligation.py`
**Verification:** `pytest -q tests/test_recall_obligation.py`

### Task 2: Build obligation inference from query + scope + metadata filter
**Files:**
- Modify: `app/rag/policy/must_recall_auto.py`
- Test: `tests/test_tag_must_recall_policy.py`
**Verification:** `pytest -q tests/test_tag_must_recall_policy.py`

### Task 3: Emit must-recall proof object in metrics/query_debug/retrieval_trace
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 4: Add deterministic proof auditor script for offline replay
**Files:**
- Add: `scripts/must_recall_proof_audit.py`
- Test: `tests/test_must_recall_proof_audit.py`
**Verification:** `pytest -q tests/test_must_recall_proof_audit.py`

### Task 5: Document proof semantics and fail taxonomy
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/regression_gate.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/regression_gate.md`

---

## G2 — Learned-Assist Router (Deterministic Fail-Safe) (Tasks 6-10)

### Task 6: Add intent training dataset exporter from retrieval traces
**Files:**
- Add: `scripts/export_intent_router_training.py`
- Test: `tests/test_export_intent_router_training.py`
**Verification:** `pytest -q tests/test_export_intent_router_training.py`

### Task 7: Add compact learned router model loader + schema guard
**Files:**
- Add: `app/rag/policy/intent_router_model.py`
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 8: Integrate learned router hinting with deterministic fallback in intent router
**Files:**
- Modify: `app/rag/policy/intent_router.py`
- Test: `tests/test_intent_router.py`
**Verification:** `pytest -q tests/test_intent_router.py`

### Task 9: Add learned-router diagnostics and confidence gate in orchestrator
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 10: Add model-generation script + CI artifact path for learned router
**Files:**
- Add: `scripts/generate_intent_router_model.py`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

---

## G3 — Iterative Retrieval Reasoning (Contextual+Gap-Aware) (Tasks 11-15)

### Task 11: Add evidence-gap detector for first-pass citation deficits
**Files:**
- Add: `app/rag/retrieval/evidence_gap.py`
- Test: `tests/test_evidence_gap.py`
**Verification:** `pytest -q tests/test_evidence_gap.py`

### Task 12: Add deterministic gap-driven follow-up query planner
**Files:**
- Modify: `app/rag/retrieval/contextual_followup.py`
- Test: `tests/test_contextual_followup.py`
**Verification:** `pytest -q tests/test_contextual_followup.py`

### Task 13: Integrate bounded iterative pass controller (max hops / latency budget)
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_secondary_pass.py`
**Verification:** `pytest -q tests/test_retrieval_secondary_pass.py`

### Task 14: Emit iterative-pass diagnostics and per-hop contribution counters
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 15: Document iterative retrieval playbook and rollback switch
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/retrieval_release_notes.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/retrieval_release_notes.md`

---

## G4 — TAG Global Planning and Join Risk Closure (Tasks 16-20)

### Task 16: Add join-statistics snapshot utility for TAG planner inputs
**Files:**
- Add: `app/services/table_join_stats.py`
- Test: `tests/test_table_join_stats.py`
**Verification:** `pytest -q tests/test_table_join_stats.py`

### Task 17: Add beam-search style multi-join planner scoring with bounded states
**Files:**
- Modify: `app/services/table_schema_graph.py`
- Test: `tests/test_table_schema_graph.py`
**Verification:** `pytest -q tests/test_table_schema_graph.py`

### Task 18: Add join-plan risk contract (`fanout_explosive`, `selectivity_unknown`) in TAG response
**Files:**
- Modify: `app/services/table_tag_service.py`
- Modify: `app/services/chat_tag_service.py`
- Test: `tests/test_table_tag_ambiguity.py`
**Verification:** `pytest -q tests/test_table_tag_ambiguity.py`

### Task 19: Add dry-run SQL cardinality validator for generated multi-table plans
**Files:**
- Modify: `app/services/table_tag_service.py`
- Test: `tests/test_table_tag_schema_linking.py`
**Verification:** `pytest -q tests/test_table_tag_schema_linking.py`

### Task 20: Update TAG runbook with global-plan diagnostics and fail reasons
**Files:**
- Modify: `docs/guides/table_tag.md`
**Verification:** `ruff check docs/guides/table_tag.md`

---

## G5 — Productionizing ColBERT/Sparse Channels (Tasks 21-25)

### Task 21: Add ColBERT provider healthcheck + warmup guard in reranker factory
**Files:**
- Modify: `app/rag/reranker/factory.py`
- Modify: `app/rag/reranker/colbert.py`
- Test: `tests/test_reranker_factory.py`
**Verification:** `pytest -q tests/test_reranker_factory.py`

### Task 22: Add ColBERT ANN retrieval readiness gate + diagnostics exposure
**Files:**
- Modify: `app/rag/retrieval/colbert_ann.py`
- Test: `tests/test_colbert_ann_retrieval.py`
**Verification:** `pytest -q tests/test_colbert_ann_retrieval.py`

### Task 23: Harden sparse index lifecycle (persist/refresh/version token)
**Files:**
- Modify: `app/rag/retrieval/sparse.py`
- Test: `tests/test_sparse_retriever.py`
**Verification:** `pytest -q tests/test_sparse_retriever.py`

### Task 24: Add channel budget auto-calibration from offline ablation artifacts
**Files:**
- Add: `scripts/generate_channel_budget_policy.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_generate_channel_budget_policy.py`
**Verification:** `pytest -q tests/test_generate_channel_budget_policy.py`

### Task 25: Extend CI bounded retrieval gate for ColBERT+sparse coverage slices
**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

---

## G6 — Feedback→Train→Canary→Rollback Automation (Tasks 26-30)

### Task 26: Add nightly hard-negative miner from feedback + retrieval traces
**Files:**
- Add: `scripts/mine_hard_negatives_nightly.py`
- Test: `tests/test_mine_hard_negatives_nightly.py`
**Verification:** `pytest -q tests/test_mine_hard_negatives_nightly.py`

### Task 27: Add scheduled LTR retraining workflow runner with lineage manifests
**Files:**
- Add: `scripts/run_ltr_nightly_cycle.py`
- Test: `tests/test_ltr_nightly_cycle.py`
**Verification:** `pytest -q tests/test_ltr_nightly_cycle.py`

### Task 28: Add canary apply helper with bounded activation policy
**Files:**
- Modify: `app/services/ltr_model_registry.py`
- Test: `tests/test_ltr_model_registry.py`
**Verification:** `pytest -q tests/test_ltr_model_registry.py`

### Task 29: Add online degradation monitor -> rollback trigger executor
**Files:**
- Add: `scripts/ltr_online_rollback_daemon.py`
- Test: `tests/test_ltr_registry_rollback_policy.py`
**Verification:** `pytest -q tests/test_ltr_registry_rollback_policy.py`

### Task 30: Document fully automated learning loop operating model
**Files:**
- Modify: `docs/guides/reranking_ltr.md`
- Modify: `docs/guides/release_gate.md`
**Verification:** `ruff check docs/guides/reranking_ltr.md docs/guides/release_gate.md`

---

## G7 — Parse-Quality Self-Healing Loop (Tasks 31-35)

### Task 31: Add parse-risk reparse scheduler from retrieval risk artifacts
**Files:**
- Add: `scripts/schedule_parse_repair.py`
- Test: `tests/test_schedule_parse_repair.py`
**Verification:** `pytest -q tests/test_schedule_parse_repair.py`

### Task 32: Add parser strategy recommendation policy by document profile
**Files:**
- Add: `app/services/parser_strategy_policy.py`
- Test: `tests/test_parser_strategy_policy.py`
**Verification:** `pytest -q tests/test_parser_strategy_policy.py`

### Task 33: Add post-reparse verification gate comparing risk-tail shrinkage
**Files:**
- Add: `scripts/verify_parse_repair_gate.py`
- Test: `tests/test_verify_parse_repair_gate.py`
**Verification:** `pytest -q tests/test_verify_parse_repair_gate.py`

### Task 34: Integrate parse repair actions into retrieval diagnostics metadata
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Task 35: Update parse-risk remediation runbook with auto-healing path
**Files:**
- Modify: `docs/guides/parse_quality_retrieval_diagnostics.md`
**Verification:** `ruff check docs/guides/parse_quality_retrieval_diagnostics.md`

---

## G8 — Multi-Hop/Reasoning Evaluation Maturity (Tasks 36-40)

### Task 36: Add multi-hop regression case schema extensions (`reasoning_hops`, `evidence_chain`)
**Files:**
- Modify: `app/api/schemas/regression.py`
- Test: `tests/test_regression_schema.py`
**Verification:** `pytest -q tests/test_regression_schema.py`

### Task 37: Add multi-hop citation chain scorer (path completeness / order consistency)
**Files:**
- Add: `app/rag/evaluation/multihop.py`
- Test: `tests/test_multihop_evaluation.py`
**Verification:** `pytest -q tests/test_multihop_evaluation.py`

### Task 38: Extend regression gate with multi-hop quality thresholds
**Files:**
- Modify: `scripts/regression_gate.py`
- Test: `tests/test_regression_gate.py`
**Verification:** `pytest -q tests/test_regression_gate.py`

### Task 39: Add CI artifact for multi-hop diagnostics summary
**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`
**Verification:** `pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py`

### Task 40: Update evaluation maturity model with multi-hop and proof-coverage tiers
**Files:**
- Modify: `docs/guides/evaluation_maturity_model.md`
- Modify: `docs/guides/regression_gate.md`
**Verification:** `ruff check docs/guides/evaluation_maturity_model.md docs/guides/regression_gate.md`

