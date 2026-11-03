# Agent Note: KG query expansion ownership

Status: implemented

## Problem

`_run_retrieval_kg_query_expansion_phase` assembled the tenant/document/dataset scope, called KG search, filtered and ranked entities, and built query variants inline. The existing KG expansion module was not used by production retrieval, so its sync/async behavior and stricter response contract did not govern the actual phase.

## Decision

The orchestrator builds a typed `KGQueryRequest` from the current retrieval scope and resolved expansion settings. `app.rag.retrieval.orchestration.kg_query_expansion` owns KG search, entity validation, filtering, ranking and expanded query construction. The phase copies the typed outcome into the existing diagnostics fields and raises only rejected top-level response contracts through `raise_for_rejected_response`.

The separate KG chunk-injection sync bridge returns the pipeline result directly. It does not convert a non-object response to `{}`, so a broken result cannot masquerade as an empty KG search.

The existing `_run_kg_search_sync` bridge remains for the separate KG chunk-injection path, which fetches candidate documents rather than query variants. This is separate from model-based query expansion.

## Alternatives considered

- Keep KG search and entity processing in the orchestrator: it avoids adapting the current phase, but leaves scope and entity policy duplicated and bypasses the tested sync/async owner; not selected.
- Route chunk injection through the query-expansion owner: it would provide one KG entry point, but query expansion returns text variants while injection needs scoped document candidates; not selected.

## Consequences

The KG query phase and native async expansion now share one scope and entity policy. A non-object KG response becomes an explicit contract error; malformed entities and optional service failures remain in `kg_query_expansion_error` and produce no expansion queries. The separate chunk-injection sync bridge remains until that operation receives its own owner.

## Verification

- `ruff check .` passes.
- `ruff format --check app/rag/retrieval/orchestrator.py` passes.
- `py_compile` passes for `app/rag/retrieval/orchestrator.py`.
- Import smoke check for `app.rag.retrieval.orchestrator` passes.
- Python tests were not run per user instruction.
- The KG sync bridge contract was statically checked against `KGEngine.search` and `pipeline.kg_search`; Python tests were not run.
