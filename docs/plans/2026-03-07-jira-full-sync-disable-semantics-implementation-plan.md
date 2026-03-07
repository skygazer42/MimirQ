# Jira Full Sync Disable Semantics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add best-effort full-sync reconciliation for `jira_project` so removed or newly hidden Jira issues are soft-disabled instead of remaining searchable forever.

**Architecture:** Keep the implementation local to the Jira connector executor and reuse the repo's existing connector reconciliation patterns. Track the issue URLs observed during a full Jira listing, only reconcile when the listing is complete, and soft-disable previously connector-managed Jira issue documents for the same tenant/dataset/base URL/project that no longer appear in the current full sync.

**Tech Stack:** FastAPI, SQLAlchemy, httpx, existing connector run metadata, pytest

---

### Task 1: Add failing Jira full-sync reconciliation tests

**Files:**
- Create: `tests/test_jira_connector_full_sync_disable_semantics.py`
- Test: `tests/test_jira_connector_full_sync_disable_semantics.py`

**Step 1: Write the failing test**

Add focused tests that assert:
- `_execute_jira_project_run(...)` triggers Jira full-sync reconciliation when `sync_mode="full"` and the Jira listing is complete
- `_execute_jira_project_run(...)` does not reconcile when the run is incremental
- the Jira reconciliation helper soft-disables connector-managed docs whose issue URL is missing from the latest full-sync result

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_jira_connector_full_sync_disable_semantics.py -q`
Expected: FAIL because Jira full-sync reconciliation does not exist yet.

**Step 3: Write minimal implementation**

Implement:
- a Jira helper that scans connector-managed documents for the same tenant/dataset/base URL/project and disables missing issue documents
- full-sync executor bookkeeping for observed issue URLs, listing completeness, and reconciliation stats

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_jira_connector_full_sync_disable_semantics.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_jira_connector_full_sync_disable_semantics.py app/api/v1/connectors.py docs/plans/2026-03-07-jira-full-sync-disable-semantics-implementation-plan.md
git commit -m "feat: reconcile missing jira issues on full sync"
```

### Task 2: Run focused connector regression

**Files:**
- Modify only if regressions require fixes

**Step 1: Run focused verification**

Run:

```bash
pytest tests/test_jira_connector_full_sync_disable_semantics.py tests/test_jira_connector_acl_inheritance_unit.py tests/test_connector_saved_state_resume.py tests/test_connector_acl_delta_sync_unit.py -q
```

Expected: PASS.

**Step 2: Commit follow-up fixes if needed**

```bash
git add app/api/v1/connectors.py tests/test_jira_connector_full_sync_disable_semantics.py
git commit -m "fix: stabilize jira full sync reconciliation"
```

### Task 3: Land and clean up

**Files:**
- Modify issue/run metadata only if needed

**Step 1: Close the task**

Run:

```bash
bd close MimirQ-ygdj.10 --reason "Implemented Jira full-sync disable semantics"
```

Expected: issue closed with acceptance slice reflected in the note.

**Step 2: Sync and push**

Run:

```bash
git pull --rebase
bd sync
git push
```

Expected: local branch and remote branch both updated.

**Step 3: Merge back to main and remove the temporary worktree**

Run:

```bash
git checkout main
git merge --ff-only mimirq-ygdj10-jira-full-sync
git push origin main
git branch -d mimirq-ygdj10-jira-full-sync
git worktree remove .worktrees/mimirq-ygdj10-jira-full-sync
```

Expected: only `main` remains as the long-lived branch.
