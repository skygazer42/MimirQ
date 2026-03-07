# Jira Cloud Connector Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a first enterprise SaaS connector, `jira_project`, that syncs Jira Cloud issues end-to-end through the shared connector registry with incremental state, ACL-aware ingestion, tests, and operator docs.

**Architecture:** Reuse the existing connector registry, schema validation, run scheduling, and saved-state contract. Implement `jira_project` as a focused Jira Cloud issue/project connector that fetches issues from Jira REST API, renders stable local HTML for ingestion, tags the result with connector metadata, and applies best-effort source ACL inheritance from Jira visibility/security signals.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, httpx, existing document ingestion helpers, connector saved-state service, pytest

---

### Task 1: Write the first failing API tests for `jira_project`

**Files:**
- Modify: `tests/test_connectors_endpoints.py`
- Test: `tests/test_connectors_endpoints.py`

**Step 1: Write the failing test**

Add tests that assert:
- `GET /api/v1/connectors` includes `jira_project`
- `supports_incremental=true` and `supports_resume=false`
- `POST /api/v1/connectors/runs` accepts a minimal Jira config and redacts auth secrets

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_connectors_endpoints.py -q`
Expected: FAIL because `jira_project` is not in the registry and its schema is unsupported.

**Step 3: Write minimal implementation**

Add the connector definition and schema/dispatch support only.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_connectors_endpoints.py -q`
Expected: PASS for the new Jira endpoint assertions.

**Step 5: Commit**

```bash
git add tests/test_connectors_endpoints.py app/services/connector_registry.py app/api/schemas/connector.py app/api/v1/connectors.py app/tasks/jobs.py app/api/schemas/connector_acl.py
git commit -m "feat: add jira project connector api surface"
```

### Task 2: Add failing unit tests for Jira helper behavior

**Files:**
- Modify: `tests/test_confluence_connector_unit.py`
- Test: `tests/test_confluence_connector_unit.py`

**Step 1: Write the failing test**

Add Jira helper unit tests that cover:
- Jira API base normalization
- Jira principal normalization for group, role, and security-level signals
- Jira issue HTML rendering exposes ticket sections that work well with `jira_ticket`
- Jira incremental timestamp extraction chooses `fields.updated`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_confluence_connector_unit.py -q`
Expected: FAIL because the Jira helper functions do not exist yet.

**Step 3: Write minimal implementation**

Implement small pure helper functions in `app/api/v1/connectors.py` and export nothing new publicly.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_confluence_connector_unit.py -q`
Expected: PASS for the Jira helper tests.

**Step 5: Commit**

```bash
git add tests/test_confluence_connector_unit.py app/api/v1/connectors.py
git commit -m "feat: add jira connector helpers"
```

### Task 3: Add failing executor/ACL tests for Jira ingestion

**Files:**
- Create: `tests/test_jira_connector_acl_inheritance_unit.py`
- Test: `tests/test_jira_connector_acl_inheritance_unit.py`

**Step 1: Write the failing test**

Add an async unit test that stubs Jira API responses and verifies:
- `_execute_jira_project_run(...)` ingests at least one issue
- issue metadata contains connector fields and `source_last_modified_at`
- source ACL inheritance maps Jira source principals into doc ACL group ids
- ACL delta sync stats/audit fields are recorded

Use a fake run with:
- `connector_id="jira_project"`
- `chunk_strategy="jira_ticket"`
- `source_acl.mode="inherit"`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_jira_connector_acl_inheritance_unit.py -q`
Expected: FAIL because the Jira executor does not exist yet.

**Step 3: Write minimal implementation**

Implement:
- Jira REST search execution
- best-effort ACL derivation from issue security/comment visibility
- local HTML ingestion
- connector metadata patching
- saved-state friendly `last_modified` stats updates

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_jira_connector_acl_inheritance_unit.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_jira_connector_acl_inheritance_unit.py app/api/v1/connectors.py
git commit -m "feat: implement jira connector execution"
```

### Task 4: Extend validation, scheduling, and saved-state coverage

**Files:**
- Modify: `tests/test_connector_validate_endpoint_unit.py`
- Modify: `tests/test_connector_sync_state.py`
- Modify: `app/api/v1/connectors.py`
- Modify: `app/services/connector_registry.py`

**Step 1: Write the failing test**

Add tests that assert:
- validate endpoint accepts/redacts Jira config
- saved state persists Jira `last_modified`
- scheduled/config run dispatch accepts `jira_project`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_connector_validate_endpoint_unit.py tests/test_connector_sync_state.py -q`
Expected: FAIL because Jira is missing from validation/state policy/dispatch.

**Step 3: Write minimal implementation**

Wire Jira through:
- `_validate_connector_schema(...)`
- `_best_effort_connectivity_checks(...)`
- `create_connector_run`
- `run_connector_config`
- `scheduled_tick`
- worker-side job dispatch

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_connector_validate_endpoint_unit.py tests/test_connector_sync_state.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_connector_validate_endpoint_unit.py tests/test_connector_sync_state.py app/api/v1/connectors.py app/services/connector_registry.py app/tasks/jobs.py
git commit -m "feat: wire jira connector into validation and scheduling"
```

### Task 5: Document the connector and ACL mapping rules

**Files:**
- Modify: `docs/guides/connectors.md`
- Modify: `docs/guides/connector_acl_inheritance.md`

**Step 1: Write the docs changes**

Document:
- why Jira Cloud was chosen as the first enterprise SaaS connector
- required config fields and auth modes
- incremental sync semantics
- Jira source principal key conventions
- current ACL limits and fail-closed behavior

**Step 2: Run docs spot-check**

Run: `rg -n "jira_project|jira:" docs/guides/connectors.md docs/guides/connector_acl_inheritance.md`
Expected: Jira sections exist in both docs.

**Step 3: Commit**

```bash
git add docs/guides/connectors.md docs/guides/connector_acl_inheritance.md docs/plans/2026-03-07-jira-cloud-connector-implementation-plan.md
git commit -m "docs: add jira connector operator guidance"
```

### Task 6: Final verification and session landing

**Files:**
- Modify only if test failures require fixes

**Step 1: Run focused verification**

Run:

```bash
pytest tests/test_connectors_endpoints.py tests/test_connector_validate_endpoint_unit.py tests/test_connector_sync_state.py tests/test_confluence_connector_unit.py tests/test_jira_connector_acl_inheritance_unit.py -q
```

Expected: PASS.

**Step 2: Run broader regression if time permits**

Run:

```bash
pytest tests/test_connector_source_acl_mapping.py tests/test_connector_source_acl_schema.py tests/test_confluence_connector_acl_inheritance_unit.py tests/test_github_connector_team_acl_mapping_unit.py tests/test_drive_connector_acl_inheritance_unit.py -q
```

Expected: PASS.

**Step 3: Update bead**

Run:

```bash
bd close MimirQ-ygdj.3
```

If not complete, keep `in_progress` and file follow-up beads for scoped gaps.

**Step 4: Sync and push**

Run:

```bash
git pull --rebase
bd sync
git push
git status
```

Expected: branch is up to date with origin and the Jira connector work is pushed.

**Step 5: Handoff**

Summarize:
- what shipped
- which Jira ACL cases are covered
- which follow-up issues remain, if any
