# Agent Note: Dataset fusion map validation owner

Status: implemented

## Problem

`DatasetRAGDefaults` declares fusion maps as `dict[str, int]` or `dict[str, float]`, but its after-model validator repeated dictionary checks and cast each value only to discard the converted result. Pydantic already owns the external shape and value-type boundary.

## Decision

Pydantic validates the declared fusion map shape and numeric types. The `DatasetRAGDefaults` model validator retains its dataset-specific fusion channel allowlist. Nonnegative and upper bounds remain in `ChatRAGConfig` after dataset defaults merge, where the effective request is normalized.

## Alternatives considered

- Keep checking and converting every value in the after-validator: this appears defensive, but duplicates field validation and can accept behavior outside the declared type when internal model construction bypasses normal validation.
- Move effective fusion bounds into dataset metadata validation: this would change where invalid stored defaults fail and risks rejecting legacy values before a chat request applies its effective contract.

## Consequences

Normal API and metadata parsing has one owner for map/value typing, while channel allowlisting and effective request bounds remain explicit. Unsupported channel names still fail schema validation. Python tests were not run per user instruction.

## Verification

Ruff check, Ruff format --check, `git diff --check`, and stale-helper scanning passed. Dataset route and `rag_defaults` service call sites were reviewed. Python tests and runtime validation were not run.
