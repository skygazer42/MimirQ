# Agent Note: Corpus cache invalidation transaction

Status: implemented

## Problem

The dataset-scope cache token path generated a token even when the tenant-scoped dataset row was missing. Cache invalidation also treated `Session.flush()` as optional and ignored its failures, while the observability endpoint returned success without committing the timestamp used to rotate the cache token.

## Decision

`resolve_corpus_cache_token` returns `None` when a requested single dataset does not exist in the tenant. `invalidate_dataset_cache_namespace` updates the dataset revision and requires the typed SQLAlchemy `Session.flush()` to succeed, but it does not commit; transaction ownership stays with its callers.

The observability endpoint commits the update. KG jobs retain their existing commit/rollback policy. RTBF retries the complete dataset set after rolling back a failed attempt. Retention treats cache invalidation as best-effort, rolls back a failed invalidation transaction, logs the failure, and preserves its completed archive/delete work.

## Alternatives considered

- Commit inside the cache-token service: this would persist the token update, but could also commit unrelated work owned by KG, RTBF, retention, or API callers.
- Keep the optional flush and return a token after failure: this can report success with a stale corpus revision and leave a failed SQLAlchemy session for the caller.

## Consequences

Successful manual invalidation persists the new dataset revision. Missing datasets do not produce cache tokens. Database failures remain visible to callers, while explicitly best-effort jobs can recover their session and continue their own policy. The token format and cache key schema are unchanged.

## Verification

Ruff check, Ruff format --check, and `git diff --check` passed for the touched Python files. Call sites were inspected for commit/rollback ownership. Python tests and database/Redis runtime checks were not run per user instruction.
