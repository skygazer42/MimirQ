# Finish Open Wave C/Wave D Tasks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close all currently open Wave C and Wave D beads tasks by finishing the missing claim-verifier/NLI chain, LTR rollout docs and gate thresholds, index-drift persistence/replay/API, and the ColBERT bounded gate + release-gate documentation path.

**Architecture:** Reuse the partially implemented local WIP already present in the working tree instead of rebuilding from scratch. Treat the remaining work as four bounded slices: Wave C claim verifier, Wave C gate/docs, Wave D index drift, and Wave D ColBERT/release gate/docs. Prefer additive schemas/services and targeted CLI/API surfaces over broad refactors.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, GitHub Actions CI, project docs under `docs/guides`, bounded CLI scripts under `scripts/`.

---

### Task 1: Finish Wave C claim verifier contract and fallback path

**Files:**
- Create: `app/rag/core/claim_nli_verifier.py`
- Modify: `app/core/config.py`
- Modify: `app/rag/core/text.py`
- Modify: `app/rag/core/claim_evidence.py`
- Modify: `app/rag/engine.py`
- Modify: `app/rag/pipelines/langgraph.py`
- Modify: `tests/test_settings_retrieval_validation.py`
- Modify: `tests/test_claim_check.py`
- Keep: `tests/test_claim_verifier_diagnostics.py`

**Step 1: Write the failing tests**

- Add config validation tests for NLI verifier mode/provider fields.
- Add claim-check tests that prove the fallback chain is observable and bounded when NLI is disabled/unavailable/enabled.

**Step 2: Run tests to verify they fail**

Run:
```bash
pytest -q tests/test_settings_retrieval_validation.py tests/test_claim_check.py tests/test_claim_verifier_diagnostics.py
```

**Step 3: Write minimal implementation**

- Add off-by-default NLI verifier settings and validation.
- Add a bounded NLI verifier contract helper with explicit availability/result metadata.
- Thread the fallback chain through text and claim-evidence checking without changing existing default behavior.

**Step 4: Run tests to verify they pass**

Run:
```bash
pytest -q tests/test_settings_retrieval_validation.py tests/test_claim_check.py tests/test_claim_verifier_diagnostics.py
```

### Task 2: Finish Wave C gate/runbook/documentation gap

**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/rag_optimization.md`
- Modify: `docs/guides/reranking_ltr.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/release_gate.py`
- Modify: `docs/guides/release_gate.md`
- Add/Modify: tests covering CI/release-gate wiring if needed

**Step 1: Write the failing tests**

- Add or extend release-gate/CI-oriented tests for drift-class thresholds and benchmark slice inputs before changing workflow/docs.

**Step 2: Run tests to verify they fail**

Run:
```bash
pytest -q tests/test_retrieval_regression_slo_gate.py tests/test_ci_retrieval_only_bounded_gate_workflow.py tests/test_claim_check.py
```

**Step 3: Write minimal implementation**

- Document claim verifier modes plus diagnostics fields.
- Update the LTR rollout guide to match already-implemented canary/rollback behavior.
- Wire the gate workflow and release gate to honor the intended drift-threshold/benchmark inputs.

**Step 4: Run tests and doc checks**

Run:
```bash
pytest -q tests/test_retrieval_regression_slo_gate.py tests/test_ci_retrieval_only_bounded_gate_workflow.py tests/test_claim_check.py
ruff check docs/guides/retrieval_debugging.md docs/guides/rag_optimization.md docs/guides/reranking_ltr.md docs/guides/release_gate.md
```

### Task 3: Build Wave D index-drift persistence, replay, and API

**Files:**
- Add: `app/models/index_drift_item.py`
- Modify: `app/services/index_audit_service.py`
- Modify: `app/api/v1/documents.py`
- Modify: `app/api/v1/observability.py`
- Add: `app/api/schemas/observability.py` or extend the existing observability schema location used by the router
- Add: `scripts/replay_index_drift.py`
- Add: `tests/test_documents_chunk_operations.py`
- Add: `tests/test_documents_chunk_patch_consistency.py`
- Add: `tests/test_replay_index_drift.py`
- Add: `tests/test_observability_index_drift_endpoint.py`

**Step 1: Write the failing tests**

- Add store-level tests for durable drift records.
- Add delete/disable strict-mode tests that require drift-item persistence and 409 behavior.
- Add replay CLI tests and list/resolve endpoint tests.

**Step 2: Run tests to verify they fail**

Run:
```bash
pytest -q tests/test_documents_chunk_operations.py tests/test_documents_chunk_patch_consistency.py tests/test_replay_index_drift.py tests/test_observability_index_drift_endpoint.py
```

**Step 3: Write minimal implementation**

- Introduce a durable drift item record/service.
- Make delete/disable chunk operations emit/store drift items and respect strict mode.
- Add bounded replay CLI and observability list/resolve API.

**Step 4: Run tests to verify they pass**

Run:
```bash
pytest -q tests/test_documents_chunk_operations.py tests/test_documents_chunk_patch_consistency.py tests/test_replay_index_drift.py tests/test_observability_index_drift_endpoint.py
```

### Task 4: Finish Wave D ColBERT bounded gate and rollout docs

**Files:**
- Add: `tests/test_colbert_retrieval_regression.py`
- Modify: `tests/test_retrieval_ablation.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/release_gate.py`
- Modify: `docs/guides/release_gate.md`
- Modify: `docs/guides/retrieval_release_notes.md`
- Modify: `docs/guides/colbert_ann_retrieval.md`
- Add: any bounded fixture JSON needed under `data/sample/`

**Step 1: Write the failing tests**

- Add bounded ColBERT regression fixture/tests.
- Extend release-gate tests to require the hybrid bounded queryset artifact input path.

**Step 2: Run tests to verify they fail**

Run:
```bash
pytest -q tests/test_colbert_retrieval_regression.py tests/test_retrieval_ablation.py tests/test_retrieval_regression_slo_gate.py
```

**Step 3: Write minimal implementation**

- Add the missing bounded ColBERT fixture/test path.
- Wire release gate + CI usage to the hybrid bounded queryset artifact.
- Document interpretation and rollout criteria for hybrid + ColBERT artifacts.

**Step 4: Run tests and doc checks**

Run:
```bash
pytest -q tests/test_colbert_retrieval_regression.py tests/test_retrieval_ablation.py tests/test_retrieval_regression_slo_gate.py tests/test_ci_hybrid_query_health_artifact.py
ruff check docs/guides/release_gate.md docs/guides/retrieval_release_notes.md docs/guides/colbert_ann_retrieval.md
```

### Task 5: Final verification and landing

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Run focused regression suites**

Run:
```bash
pytest -q tests/test_settings_retrieval_validation.py tests/test_claim_check.py tests/test_claim_verifier_diagnostics.py tests/test_ltr_rollout_workflow.py tests/test_ltr_rollout_gate.py tests/test_ltr_registry_rollback_policy.py tests/test_documents_chunk_operations.py tests/test_documents_chunk_patch_consistency.py tests/test_replay_index_drift.py tests/test_observability_index_drift_endpoint.py tests/test_colbert_retrieval_regression.py tests/test_retrieval_ablation.py tests/test_retrieval_regression_slo_gate.py tests/test_ci_hybrid_query_health_artifact.py tests/test_ci_retrieval_only_bounded_gate_workflow.py
```

**Step 2: Run repository quality gates**

Run:
```bash
ruff check app scripts tests docs/guides
```

**Step 3: Close/Sync issue state**

Run:
```bash
bd --sandbox close MimirQ-uqd9.25 MimirQ-uqd9.26 MimirQ-uqd9.28 MimirQ-uqd9.34 MimirQ-uqd9.37 MimirQ-uqd9.38
bd --sandbox close MimirQ-4hil.4 MimirQ-4hil.5 MimirQ-4hil.6 MimirQ-4hil.7 MimirQ-4hil.8 MimirQ-4hil.38 MimirQ-4hil.39 MimirQ-4hil.40
```

**Step 4: Commit, sync, pull, push**

Run:
```bash
git status
git add <files>
bd sync
git commit -m "feat: finish remaining wave c and wave d gaps"
bd sync
git pull --rebase
git push
git status
```
