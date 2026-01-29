# Import & Optional-Dependency Policy

This document defines the hard rules for imports and optional dependency degradation in MimirQ.

## Goals

- Avoid hidden degradation caused by `try import + broad except` (silent partial failures).
- Make every "best-effort" path observable: logs + structured reason returned to caller when applicable.
- Keep behavior stable and debuggable in enterprise deployments.

## Rules

### 1) Internal modules (`app.*`)

- Do **not** use `try/except` to "degrade" internal imports.
- If there is a circular import or init-order issue, fix it by refactoring (layering/adapters), not by swallowing exceptions.

### 2) Optional third-party dependencies

At the import boundary:

- Only catch `ImportError` (true missing dependency).
- Never catch `Exception`/`BaseException` to hide version mismatch, syntax errors, or real bugs.

Use the shared helpers:

- `app.core.optional_deps.optional_import("pkg", feature="...")`
  - Returns the module or `None`
  - Emits a warning log with remediation (install hint)
- `app.core.optional_deps.require_dependency("pkg", feature="...")`
  - Raises `RuntimeError` on `ImportError` with remediation
  - Use when a feature is enabled/selected and should fail-fast

### 3) Degraded behavior must be explicit

If a feature degrades due to missing dependencies:

- Emit a warning log including:
  - `feature`, `dependency`, `reason`, `remediation`
- Return a structured degraded reason when possible (e.g. API response payloads / job stats).

## Notes

- `AGENTS.md` mentions the Corridor MCP tool for plan/threat analysis, but the current environment may not have it configured.
  When unavailable, do a manual security review and keep changes small, observable, and test-covered.

