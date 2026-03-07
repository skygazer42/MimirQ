# GitHub Removed File Reconciliation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reconcile GitHub files removed upstream during incremental sync so connector state prunes stale manifest entries and previously connector-managed documents are soft-disabled in a bounded, auditable way.

**Architecture:** Keep the change scoped to `github_repo`. Extend the existing incremental manifest flow in `app/api/v1/connectors.py` so the executor detects previously tracked paths that no longer exist in the current repository tree, removes those paths from the in-run manifest snapshot, and soft-disables matching connector-managed documents by `doc_metadata.source_url`. Update connector sync-state persistence so an explicitly empty `source_manifest` overwrites stale saved state instead of preserving removed paths forever.

**Tech Stack:** Python, FastAPI, SQLAlchemy ORM objects, pytest.

---

### Task 1: Specify removed-path behavior with failing tests

**Files:**
- Modify: `tests/test_connector_saved_state_resume.py`
- Modify: `tests/test_connector_sync_state.py`

**Steps:**
1. Write a failing executor test proving incremental `github_repo` sync detects a previously tracked path that no longer appears in the latest tree.
2. In that same test, assert the run stats prune the removed path from `source_manifest`.
3. In that same test, assert the executor calls a dedicated reconciliation helper for the removed path and records explicit removal stats.
4. Write a failing sync-state test proving `build_persisted_state(...)` overwrites a previous `source_manifest` with an explicitly empty manifest instead of preserving stale entries.
5. Run:
   - `pytest tests/test_connector_saved_state_resume.py tests/test_connector_sync_state.py -q`
6. Verify the new assertions fail for the expected reason.

---

### Task 2: Implement bounded GitHub delete reconciliation

**Files:**
- Modify: `app/api/v1/connectors.py`
- Modify: `app/services/connector_sync_state.py`

**Steps:**
1. Add a bounded helper in `app/api/v1/connectors.py` that soft-disables connector-managed documents for a specific `source_url` by joining `ConnectorRunDocument` and `ConnectorRun`, mirroring the safety shape of the existing ACL delta helper.
2. Update `_execute_github_repo_run(...)` so it:
   - scans the returned Git tree without falsely treating paths outside the `max_files` processing window as deleted
   - computes removed tracked paths from the previous manifest
   - prunes removed paths from the in-run `source_manifest`
   - soft-disables matching documents for each removed path before finalizing stats
3. Emit explicit run stats for removed-path detection and reconciliation, keeping the schema additive and bounded.
4. Update `build_persisted_state(...)` so `source_manifest` in run stats always replaces the prior saved manifest, including the empty-manifest case.
5. Run:
   - `pytest tests/test_connector_saved_state_resume.py tests/test_connector_sync_state.py -q`
6. Confirm the new tests pass before any cleanup refactor.

---

### Task 3: Document operator-visible behavior

**Files:**
- Modify: `docs/guides/connectors.md`

**Steps:**
1. Extend the `github_repo` connector guide with incremental delete behavior:
   - removed upstream files are detected from the tracked manifest
   - saved manifest entries are pruned
   - matching connector-managed documents are soft-disabled, not hard-deleted
2. Keep the wording explicit about scope: reconciliation is bounded to connector-managed documents identified by source URL.
3. Run:
   - `pytest tests/test_connector_saved_state_resume.py tests/test_connector_sync_state.py tests/test_confluence_connector_unit.py -q`

---

### Task 4: Verify and land

**Steps:**
1. Run focused verification:
   - `pytest tests/test_connector_saved_state_resume.py tests/test_connector_sync_state.py tests/test_confluence_connector_unit.py tests/test_connector_acl_delta_sync_unit.py -q`
2. Close the task:
   - `bd close MimirQ-ygdj.9`
3. Sync and push:
   - `git pull --rebase`
   - `bd sync`
   - `git push`
   - `git status`
