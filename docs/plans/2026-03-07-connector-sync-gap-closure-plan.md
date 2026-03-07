# Connector Sync Gap Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining `MimirQ-ygdj.2` acceptance gaps by versioning saved connector state, auditing state transitions, and upgrading `github_repo` from checkpoint resume to true source-delta sync.

**Architecture:** Keep the existing shared connector registry and state helper, but extend the persisted state contract so saved config state carries a stable schema version, monotonic revision, timestamps, and a bounded audit trail. For delta semantics, use GitHub tree blob SHAs as the source-of-truth cursor: unchanged paths are skipped on later runs, changed/new paths are ingested, and partial failures only advance the saved manifest for successful items.

**Tech Stack:** Python, FastAPI, SQLAlchemy ORM, pytest, TypeScript/React docs/UI copy.

---

### Task 1: Lock the saved-state contract with tests

**Files:**
- Modify: `tests/test_connector_sync_state.py`
- Modify: `tests/test_confluence_connector_unit.py`

**Steps:**
1. Add a failing unit test for versioned persisted state:
   - expect stable metadata fields such as schema version, revision, recorded timestamp, and bounded audit history
   - expect connector-specific keys (`cursor`, `last_modified`, `source_manifest`) to remain top-level for backward compatibility
2. Add a failing unit test for `_sync_connector_config_from_run(...)`:
   - expect saved state revision to advance
   - expect a best-effort audit log event describing connector/config/run/revision and changed keys
3. Run only the new tests and confirm they fail for the missing contract.

Run: `pytest tests/test_connector_sync_state.py tests/test_confluence_connector_unit.py -q`

### Task 2: Lock GitHub true-incremental semantics with tests

**Files:**
- Modify: `tests/test_connector_saved_state_resume.py`
- Modify: `tests/test_connectors_endpoints.py`

**Steps:**
1. Add a failing executor test where saved manifest SHAs cause unchanged GitHub files to be skipped and only changed/new files are ingested.
2. Add a failing executor test for a no-op rerun where all GitHub SHAs are unchanged and zero documents are re-created.
3. Add a failing partial-failure test showing only successful delta items advance the saved manifest.
4. Update connector capability expectations so `github_repo` advertises both `supports_resume` and `supports_incremental`.
5. Run only the targeted tests and confirm they fail for the missing delta behavior.

Run: `pytest tests/test_connector_saved_state_resume.py tests/test_connectors_endpoints.py -q`

### Task 3: Implement versioned/auditable state persistence

**Files:**
- Modify: `app/services/connector_registry.py`
- Modify: `app/services/connector_sync_state.py`
- Modify: `app/api/v1/connectors.py`

**Steps:**
1. Extend connector state persistence helpers to produce a stable saved-state envelope:
   - schema version
   - monotonic revision
   - recorded timestamp
   - bounded audit history
   - top-level connector cursor keys kept intact
2. Add connector-specific manifest support for `github_repo`.
3. Update `_sync_connector_config_from_run(...)` to emit a best-effort audit log entry when saved state changes.
4. Keep resume consumers backward compatible.

Run: `pytest tests/test_connector_sync_state.py tests/test_confluence_connector_unit.py -q`

### Task 4: Implement GitHub source-delta sync

**Files:**
- Modify: `app/api/v1/connectors.py`
- Modify: `app/services/connector_registry.py`

**Steps:**
1. Promote `github_repo` to `supports_incremental=True`.
2. Use GitHub tree blob SHAs as the saved source manifest.
3. On later runs:
   - skip unchanged paths
   - ingest changed/new paths
   - keep no-op reruns cheap and explicit in stats
   - only advance saved manifest entries for successfully processed paths
4. Preserve existing resume semantics for interrupted runs.

Run: `pytest tests/test_connector_saved_state_resume.py tests/test_connectors_endpoints.py -q`

### Task 5: Document and surface the sync semantics

**Files:**
- Modify: `docs/guides/connectors.md`
- Modify: `web/components/knowledge/knowledge-settings-panel.tsx`

**Steps:**
1. Add a short “resume vs incremental” section to the connector guide.
2. Document that GitHub incremental sync uses blob SHAs and that saved state carries version/audit metadata.
3. Surface connector capabilities in the settings UI so operators can see when a source supports resume only versus true incremental sync.

Run: `pytest tests/test_connectors_endpoints.py -q`

### Task 6: Verify and land

**Steps:**
1. Run focused tests:
   - `pytest tests/test_connector_sync_state.py tests/test_confluence_connector_unit.py tests/test_connector_saved_state_resume.py tests/test_connectors_endpoints.py tests/test_connector_run_retry_resume.py -q`
2. If green, run one broader connector slice:
   - `pytest tests/test_connector_url_batch_checkpoint_resume.py tests/test_drive_connector_acl_inheritance_unit.py tests/test_github_connector_team_acl_mapping_unit.py -q`
3. Update issue status and sync:
   - `bd close MimirQ-ygdj.2`
   - `git pull --rebase`
   - `bd sync`
   - `git push`
   - `git status`
