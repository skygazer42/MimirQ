# Agent Note: Trust validated source ACL models

Status: implemented

## Problem

The connector ACL mapper receives `SourceAcl` and `ConnectorSourceAclConfig` models whose Pydantic schemas validate principals, group mappings and bounded list sizes. The mapper repeated validation with broad per-item exception handling and an `assert` that restated its inherit-mode check.

## Decision

The mapper and schema consume the Pydantic-validated `SourceAcl` and `ConnectorSourceAclConfig` fields directly. Their after-model validators deduplicate the typed principals/rules without rechecking element shapes; an invalid internal model raises instead of silently dropping a principal or mapping rule. The mapper checks `config is None` and `config.mode` at its boundary. The explicit `allow_anyone` opt-in and fallback access mode for unmapped principals remain unchanged.

## Alternatives considered

- Keep broad per-item catches and skip failing keys: this continues processing when an object is malformed, but the schema already rejects that input and the catch hides a broken internal invariant; not selected.
- Keep `_should_inherit` and the following `assert`: this separates the mode expression, but the helper cannot narrow the type and the assertion repeats the condition; not selected.

## Consequences

Validated inputs use a shorter mapping path, and failures from invalid internal model state stay visible. An invalid model can now stop ACL mapping instead of being partially ignored. Revisit this boundary only if a future caller passes raw, unvalidated connector values into the mapper.

## Verification

- Ruff check, Ruff security rules and Ruff format check pass for `app/services/connector_source_acl_mapping.py` and `app/api/schemas/connector_acl.py`.
- `py_compile` and module import smoke checks pass.
- Python tests were not run per user instruction.
