# Agent Note: Dataset defaults require a complete document scope

Status: implemented

## Problem

`resolve_single_dataset_id_for_documents` queried only distinct dataset IDs. If a request contained one missing or cross-tenant document ID plus valid IDs from one dataset, the valid subset still produced a dataset ID and its defaults could be applied to an incomplete scope.

## Decision

The helper deduplicates the requested document IDs, queries `(document_id, dataset_id)` under the tenant filter, and compares the found document IDs with the complete request set. It returns a dataset ID only when every requested document exists and all rows share one non-null dataset. Dataset metadata is read through the declared ORM field; invalid metadata remains an empty object at the JSON boundary.

## Alternatives considered

- Keep selecting distinct dataset IDs: this is shorter, but cannot detect requested documents omitted by the tenant-scoped query.
- Infer a dataset from the rows that were found: this silently applies dataset defaults to only part of the requested document scope.

## Consequences

Valid complete single-dataset scopes keep their existing defaults. Missing, cross-tenant, mixed-dataset, and unscoped requests return `None`, so callers do not infer dataset defaults from partial evidence. The API request and response shapes are unchanged. Python tests and database runtime checks were not run per user instruction.

## Verification

Ruff check, Ruff format --check, `git diff --check`, and a search of all seven production callers passed. Python tests were not run.
