# Agent Note: Commit failures follow the owning transaction boundary

Status: implemented

## Problem

Audit-only commits and compensating failure-state writes silently lost persistence errors. Background scan handlers attempted compensation on a failed transaction without first rolling it back, and could lose the original scan exception from the logs.

## Decision

The API audit branches retain the documented fail-open contract in `audit_log_service.py`. They roll back failed audit transactions and log warnings with exception tracebacks. A rollback failure propagates; there is no nested suppression that reports an unusable Session as healthy.

Profile and precheck background handlers log the original scan exception and roll back before querying the run for compensation. Failed compensation is separately rolled back and logged. Their existing background isolation policy remains; enqueue callers still return their explicit 503 when enqueue fails.

Confluence page identity and connector metadata are required writes: commit failure rolls back and propagates to the connector's item failure boundary. Optional regression progress, extraction metrics and prompt usage retain their existing sidecar policy with traceback warnings and direct rollback. Retry cleanup explicitly returns `deferred`, retains its marker and logs the failed commit traceback.

Batch precheck has two contracts. `precheck_only` requires a persisted scan and propagates failure. Optional precheck-first ingestion rolls back and logs a scan failure, retaining the committed scan so the response links to its failed record. Only scan creation failure returns no scan. Refresh failures propagate outside the optional execution boundary. The precheck worker rolls back before compensation and preserves the original exception if the compensating commit also fails.

KG completion includes the dataset corpus revision commit. Failure rolls back and propagates to the queue instead of returning a successful job with a cache token that was not persisted. The evidence repair job's separate audit remains fail-open with a traceback warning. Alias and predicate primary commits already propagate; their rollback errors now also propagate with the commit error retained in Python's exception context.

This complements [dataset audit degradation](2026-11-08-dataset-audit-degradation.md) and [document mutation contracts](2026-11-05-document-mutation-contracts.md): audit, QA statistics and optional usage counters are distinct from authoritative document/version writes. The acceptance tests also prove document version KG cleanup failure produces an HTTP 500.

## Alternatives considered

- Propagate every audit commit failure: this would turn already committed operations into apparent failures and contradict the existing audit contract.
- Keep silent compensation and rely on failed-state rows: the compensating transaction can itself fail, so rows alone cannot make the original failure observable.

## Consequences

Applying a suggested ingestion policy remains an optional convenience after the scan is committed. Its own helper already caught application failures before the outer precheck boundary was split. That helper now rolls back failed suggestions and logs their tracebacks, while the batch response retains the committed scan ID. An existing-policy 409 remains a normal no-op. Mandatory scan/dataset refresh failures outside this suggestion boundary still propagate.

Successful audit degradation does not guarantee an audit row exists; warnings now expose that loss. Primary operation commits retain their existing propagation behavior. Background failure-state persistence can still fail, but its exception and the original failure remain visible. No retry, replacement store or fabricated success value is introduced.

The API regression suite fails in 11 cases before these changes and passes afterward. Desktop acceptance tests fail in 9 cases under temporary restoration of the old silent branches and pass with the source restored. Full commands and outputs are recorded in the plan progress ledger; tests use injected Session failures without database, parser or model services.

The service regressions also prove the required/optional precheck policy when the initial scan record is committed but its worker subsequently fails. Most tests inject Session failures into real production entry points; database transport failures remain outside this validation. The existing retry-queue and task-lock test fixture failures are reproduced against the old source and remain outside this change.

The precheck response regression additionally uses real SQLAlchemy Sessions over local SQLite: the worker commits a failed scan, the request rollback expires it, and reading its ID reloads the committed row into the response. If the database cannot refresh a scan or dataset, that failure propagates. This corrects the earlier loss of a committed failed scan's response link; it does not promise refresh succeeds during a database outage.
