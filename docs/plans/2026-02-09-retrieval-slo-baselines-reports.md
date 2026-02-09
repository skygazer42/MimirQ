# Retrieval SLOs: Per-Dataset Baselines, Reports, and Update Workflow Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Turn "must recall if it exists" into a measurable contract per dataset:
- baseline query sets per dataset (gold evidence)
- deterministic gating (CI + local)
- human-readable reports with diffs when retrieval changes

**Existing hooks to reuse:**
- Regression gate CLI: `scripts/regression_gate.py`
- Retrieval SLO gate tests: `tests/test_retrieval_regression_slo_gate.py`

---

### Task 1: Define a dataset evaluation pack format (gold queries + evidence)

**Files:**
- Add: `app/eval/schema.py`
- Add: `docs/eval-pack-format.md`
- Test: `tests/test_eval_pack_schema_validation.py` (new)

**Step 1: Write failing schema validation tests**

Define an eval pack JSON schema with:
- `dataset_id`
- `version`
- `created_at`
- `queries: [{ id, query, must_recall: [{ doc_id, chunk_id? , contains_text? }] }]`

Run:
```bash
python -m pytest -q tests/test_eval_pack_schema_validation.py
```
Expected: FAIL.

**Step 2: Implement Pydantic schema**

Add strict validation:
- `dataset_id` required
- each query must have at least one `must_recall` entry
- `contains_text` is optional but must be <= N chars and ASCII-safe (for diffs)

**Step 3: Commit**

```bash
git add app/eval/schema.py docs/eval-pack-format.md tests/test_eval_pack_schema_validation.py
git commit -m "feat(eval): add eval pack schema and docs"
```

---

### Task 2: Generate reports (hit@k, recall, abstain rates) per dataset

**Files:**
- Modify: `scripts/regression_gate.py`
- Add: `app/eval/report.py`
- Test: `tests/test_eval_report_generation.py` (new)

**Step 1: Implement report generator**

For each query:
- run retrieval (evidence API core)
- compute:
  - hit@5/10/20 for each must_recall item (chunk_id match when available, else contains_text match)
  - top score
  - time_ms
  - `has_evidence` vs abstain

Output:
- JSON (machine)
- Markdown (human; include "worst 10" queries)

**Step 2: Add tests**

Use a tiny fixture dataset and deterministic retriever settings.

**Step 3: Commit**

```bash
git add scripts/regression_gate.py app/eval/report.py tests/test_eval_report_generation.py
git commit -m "feat(eval): generate per-dataset retrieval reports"
```

---

### Task 3: CI gating integration (per dataset thresholds)

**Files:**
- Add: `scripts/ci_eval_gate.py`
- Modify: `.github/workflows/ci.yml` (or equivalent)

**Step 1: Implement CI gate**

Inputs:
- pack paths (glob)
- thresholds (min recall@20, max abstain on known-evidence queries)

Behavior:
- fail if recall regresses compared to the baseline stored in the eval pack (or a committed baseline report)
- print a diff table listing regressed queries

**Step 2: Commit**

```bash
git add scripts/ci_eval_gate.py .github/workflows/ci.yml
git commit -m "ci: add per-dataset retrieval eval gate"
```

---

### Task 4: Update workflow (authoring and reviewing eval packs)

**Files:**
- Add: `docs/eval-workflow.md`
- Add: `scripts/new_eval_pack.py`

**Step 1: Authoring script**

Given:
- dataset_id
- a list of queries
The script should:
- run retrieval
- allow selecting citations as gold (interactive TUI optional; start with simple prompts)
- write a pack JSON with stable ids

**Step 2: Review guidance**

Document how to:
- add new packs
- update packs intentionally
- interpret report diffs

**Step 3: Commit**

```bash
git add docs/eval-workflow.md scripts/new_eval_pack.py
git commit -m "docs(eval): add eval pack update workflow"
```

