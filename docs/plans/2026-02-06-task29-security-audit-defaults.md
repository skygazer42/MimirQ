# Task 29: Security Audit Defaults (Hide SQL/Connection Info) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make security auditing safe-by-default by hiding SQL and DB connection details in normal API responses, while allowing owner/admin/auditor roles to view redacted versions when explicitly requested.

**Architecture:** Add small redaction helpers (SQL literal masking + DB-connection field masking). Wire them into the table query endpoints and DB catalog connector outputs. Add a lightweight audit-log record for structured table queries (store only hashes + redacted SQL). Extend the audit-log listing endpoint to support an `auditor` role and an `include_sensitive` flag (defaults to false).

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, existing audit log service (`app/services/audit_log_service.py`).

## Notes / Constraints

- Corridor MCP tool is not available in this environment (no MCP servers/resources configured), so we cannot run Corridor security analysis as requested by `AGENTS.md`.
- Redaction is best-effort and must never break product flows (keep existing fail-open style).

## Implementation Tasks

### Task 1: Tests first (RED)

**Files:**
- Add: `tests/test_task29_security_audit_defaults.py`

**Step 1: Write failing tests**

1. **SQL redaction:** redacts string literals and long numeric literals deterministically.
2. **Connection redaction:** for DB connector configs, hides connection fields by default and preserves secret redaction (`password -> "<redacted>"`).
3. **Audit listing role:** `_ensure_admin` allows tenant role `auditor`.

**Step 2: Run tests to confirm failures**

Run: `PYTHONPATH=. python -m pytest -q tests/test_task29_security_audit_defaults.py`

Expected: FAIL because the new helpers/role wiring do not exist yet.

### Task 2: Implement redaction helpers (GREEN)

**Files:**
- Add: `app/services/security_redaction.py`

**Step 1: SQL literal masking helper**

- Implement `redact_sql_literals(sql: str) -> str`:
  - Replace single-quoted literals with `'<redacted>'` (handle escaped `''`).
  - Replace long numeric literals (>= 5 digits) with `<redacted_num>`.
  - Keep query structure intact.

**Step 2: Connection-info masking helper**

- Implement `redact_connection_info(config: dict, *, enabled: bool) -> dict`:
  - If disabled: return config unchanged.
  - If enabled: mask keys like `host`, `hostname`, `port`, `database`, `db`, `username`, `user`, `dsn`, `uri`, `jdbc_url`, `connection_string`.
  - Do **not** override existing secret redaction (`password` stays `<redacted>` if already redacted).

### Task 3: Wire into table query endpoints + audit log (GREEN)

**Files:**
- Modify: `app/api/v1/dataset_tables.py`
- Modify: `app/api/schemas/table_store.py`
- Modify: `app/services/audit_log_service.py` (only if needed)

**Step 1: Role gating**

- Add a local helper to determine whether `account_id` is in `owner/admin/auditor` role (via `DatasetService.ensure_member`).

**Step 2: Hide SQL by default**

- For `query_dataset_table`: return `sql="<hidden>"` unless `include_sql=true` and caller is privileged; when privileged, return `redact_sql_literals(sql)`.
- For `ask_dataset_table`: default `sql=None`; when privileged and `include_sql=true`, include redacted SQL.

**Step 3: Emit audit log event**

- Add `audit_log_event` for table query/ask:
  - action: `table.query`
  - details: `dataset_id`, `table_id`, `sql_hash`, `sql_chars`, `sql_redacted` (only for privileged include or store always-redacted).

### Task 4: Wire into DB connector outputs (GREEN)

**Files:**
- Modify: `app/api/v1/connectors.py`

**Step 1: Mask connection info by default**

- In `_run_out` and `_config_out`, apply `redact_connection_info(..., enabled=not privileged)` for DB connector types only (`mysql_catalog`, `sqlserver_catalog`).

### Task 5: Audit logs endpoint defaults (GREEN)

**Files:**
- Modify: `app/api/v1/audit.py`

**Step 1: Add `auditor` to allowed roles**

- Extend `_ADMIN_ROLES` to include `auditor`.

**Step 2: Hide sensitive fields by default**

- Add query param `include_sensitive: bool = False`.
- When false, strip keys like `sql_redacted`, `connection`, `dsn`, etc from `details`.

### Task 6: Verification + tracker + merge

**Files:**
- Modify: `docs/plans/2026-02-06-seq-rag-improvements-tracker.md`

**Step 1: Run verification**

- Targeted: `PYTHONPATH=. python -m pytest -q tests/test_task29_security_audit_defaults.py`
- Full: `PYTHONPATH=. python -m pytest -q`

**Step 2: Update tracker**

- Mark Task 29 as done.
- Set **Next Up** to Task 30.
- Add pointer to this plan doc.

**Step 3: Commit + merge + push**

- Commit on `seq-rag-task29`.
- Fast-forward merge into `main`.
- `git push origin main`

