# Queryset Health Diff Markdown Artifact CI Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete `MimirQ-80yl` by making CI generate a human-readable `queryset health diff` Markdown artifact so PR reviewers can quickly understand metric drift, policy drift, and hard-case churn.

**Architecture:** Reuse the existing `retrieval-only-bounded-gate` job outputs (`artifacts/queryset_health.snapshot.json`) and the new diff utility (`scripts/diff_queryset_health_snapshots.py`). Add one baseline snapshot fixture under `ci/`, run the diff script in CI to produce JSON + Markdown outputs, and upload both as artifacts.

**Tech Stack:** GitHub Actions workflow YAML, Python CLI script (`scripts/diff_queryset_health_snapshots.py`), pytest workflow contract tests, Markdown docs.

---

### Task 1: Add CI Baseline Snapshot Fixture

**Files:**
- Create: `ci/queryset_health_snapshot_baseline.v1.json`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`

**Step 1: Write the failing test**

Extend workflow contract assertions to require:
- `ci/queryset_health_snapshot_baseline.v1.json` is referenced in the CI workflow.
- `scripts/diff_queryset_health_snapshots.py` is invoked.
- Markdown output path (for example `artifacts/queryset_health.diff.md`) is present in uploaded artifacts.

**Step 2: Run test to verify it fails**

Run:

```bash
pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py
```

Expected: fails because workflow does not yet reference baseline snapshot + diff markdown artifact.

**Step 3: Write minimal implementation**

Create `ci/queryset_health_snapshot_baseline.v1.json` with:
- schema `mimirq.queryset_health_snapshot.v1`
- stable policy metadata (`policy_source`, `policy_hash`)
- representative metrics/risk/degradation fields for meaningful diff output

Keep the fixture deterministic and small.

**Step 4: Run test to verify it still fails on missing workflow wiring**

Run:

```bash
pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py
```

Expected: still failing until Task 2 wires the workflow step.

---

### Task 2: Wire Snapshot Diff JSON + Markdown Generation in CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_ci_retrieval_only_bounded_gate_workflow.py`

**Step 1: Write/keep failing test coverage from Task 1**

Reuse the same test to assert CI wiring contract.

**Step 2: Implement minimal workflow changes**

In job `retrieval-only-bounded-gate`, add a step after queryset snapshot generation:

```bash
python scripts/diff_queryset_health_snapshots.py \
  --a ci/queryset_health_snapshot_baseline.v1.json \
  --b artifacts/queryset_health.snapshot.json \
  --out artifacts/queryset_health.diff.json \
  --out-md artifacts/queryset_health.diff.md
```

Then include these files in upload artifact paths:
- `artifacts/queryset_health.diff.json`
- `artifacts/queryset_health.diff.md`
- `ci/queryset_health_snapshot_baseline.v1.json`

**Step 3: Run test to verify pass**

Run:

```bash
pytest -q tests/test_ci_retrieval_only_bounded_gate_workflow.py
```

Expected: pass.

---

### Task 3: Document Reviewer Workflow for the New Artifact

**Files:**
- Modify: `docs/guides/release_gate.md`
- Modify: `scripts/README.md`
- Add/Modify Test: `tests/test_release_gate_docs.py` and/or `tests/test_queryset_health_policy_docs.py`

**Step 1: Write failing doc assertions**

Add/extend tests requiring documentation mentions:
- `queryset_health.diff.md`
- baseline fixture path
- intended review use in PR/release checks

**Step 2: Run doc test to verify failure**

Run:

```bash
pytest -q tests/test_release_gate_docs.py tests/test_queryset_health_policy_docs.py
```

Expected: fail before docs are updated.

**Step 3: Update docs minimally**

Document:
- where the markdown artifact is produced in CI
- how to interpret policy drift vs metric drift
- expected artifact paths for reviewers

**Step 4: Run doc test to verify pass**

Run:

```bash
pytest -q tests/test_release_gate_docs.py tests/test_queryset_health_policy_docs.py
```

Expected: pass.

---

### Task 4: Verify, Close Issue, and Land

**Files:**
- Modify (metadata): `.beads/issues.jsonl` via `bd`

**Step 1: Run focused quality gates**

Run:

```bash
pytest -q \
  tests/test_ci_retrieval_only_bounded_gate_workflow.py \
  tests/test_ci_retrieval_gate_workflow.py \
  tests/test_release_gate_docs.py \
  tests/test_queryset_health_policy_docs.py
ruff check \
  .github/workflows/ci.yml \
  scripts/diff_queryset_health_snapshots.py \
  tests/test_ci_retrieval_only_bounded_gate_workflow.py \
  tests/test_release_gate_docs.py \
  tests/test_queryset_health_policy_docs.py
```

Expected: all pass (note: `ruff` should only target Python files; do not pass Markdown/YAML to ruff).

**Step 2: Close `MimirQ-80yl`**

Run:

```bash
bd --no-daemon close MimirQ-80yl --reason "CI now publishes queryset health diff markdown artifact"
```

**Step 3: Sync and push**

Run:

```bash
bd --no-daemon sync
git add -A
git commit -m "ci: publish queryset health diff markdown artifact"
git pull --rebase
git push
git status
```

Expected: `git status` shows clean worktree and up-to-date with `origin/main`.
