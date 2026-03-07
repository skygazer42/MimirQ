# LTR Rollout Workflow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a bounded workflow that materializes approved evidence and selected feedback into a regression-case bundle, trains and evaluates a candidate LTR model against the current baseline, persists an auditable comparison artifact, and keeps activation manual.

**Architecture:** Add a small workflow service with pure helpers for source materialization and comparison synthesis, then wrap it in a single admin CLI under `scripts/`. Reuse the existing training script, offline eval script, and file-based LTR registry instead of re-implementing model training or activation logic.

**Tech Stack:** FastAPI backend models/services, Python CLI scripts, pytest, file-based JSON artifacts.

---

### Task 1: Define workflow helpers

**Files:**
- Create: `app/services/ltr_rollout_workflow.py`
- Test: `tests/test_ltr_rollout_workflow.py`

**Step 1: Write the failing test**

Cover:
- approved EvidenceItem rows become regression bundle items
- selected feedback rows become regression bundle items
- dataset mismatch fails closed
- comparison summary computes candidate-vs-baseline deltas

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_ltr_rollout_workflow.py`

**Step 3: Write minimal implementation**

Add helpers to:
- materialize a `mimirq.regression_cases.v1` bundle
- synthesize comparison artifacts from eval summaries
- expose stable workflow metadata for persistence

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_ltr_rollout_workflow.py`

### Task 2: Add the bounded rollout CLI

**Files:**
- Create: `scripts/prepare_ltr_rollout.py`
- Modify: `tests/test_ltr_rollout_workflow.py`

**Step 1: Write the failing test**

Cover:
- workflow writes bundle/comparison/workflow artifacts
- active baseline metadata is captured when present
- activation is not performed

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_ltr_rollout_workflow.py -k rollout`

**Step 3: Write minimal implementation**

The CLI should:
- gather approved evidence + selected feedback
- write a cases bundle
- invoke existing train/eval scripts in-process
- optionally register the candidate model
- persist workflow/comparison JSON under a workflow directory

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_ltr_rollout_workflow.py -k rollout`

### Task 3: Document the operator workflow

**Files:**
- Modify: `docs/guides/reranking_ltr.md`

**Step 1: Write the failing test**

No automated doc test required.

**Step 2: Write minimal implementation**

Document:
- source selection
- workflow outputs
- manual activation / rollback path

**Step 3: Run focused verification**

Run:
- `pytest -q tests/test_ltr_rollout_workflow.py tests/test_train_ltr_manifest_lineage.py tests/test_eval_ltr_offline_summary_lineage.py tests/test_ltr_model_registry.py tests/test_ltr_model_registry_preserves_lineage.py tests/test_feedback_to_evidence_item.py tests/test_task30_feedback_to_regression_case.py`
- `ruff check app/services/ltr_rollout_workflow.py scripts/prepare_ltr_rollout.py tests/test_ltr_rollout_workflow.py`

