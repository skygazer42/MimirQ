# Agent Note: Chat runtime typed contracts

Status: implemented

## Problem

Chat bootstrap accepted `Any` for requests and RAG templates, then used `getattr` defaults for fields owned by `ChatRequest` and `RagConfigTemplate`. Dataset metadata was also checked as a dictionary after its loader had already guaranteed that shape. Cache and persistence inputs used bare container annotations.

## Decision

The bootstrap runtime uses `ChatRequest`, `ChatRAGConfig`, and `RagConfigTemplate` at the existing internal boundary. It reads their declared fields directly and consumes dataset metadata as the dictionary returned by `load_dataset_metadata`. Nullable template counters still normalize `None` to zero. Cache key resolution types its database dependency as `Session`, matching `resolve_corpus_cache_token`.

Cache payload parsing remains a serialized Redis boundary: dictionary and citation shape checks, best-effort cache failure handling, and singleflight follower behavior stay in place. Optional memory lookup, template usage rollback, transaction order, cache keys, tenant/account/document scope, lease timing, timeout, and cancellation behavior are unchanged.

## Alternatives considered

- Keep `Any` and defensive `getattr` defaults: this supports objects that do not satisfy the existing request and ORM contracts, but obscures missing internal fields and duplicates schema guarantees.
- Remove Redis payload checks with the internal checks: cached JSON is externally serialized state, so its shape still requires validation.

## Consequences

Valid API requests and ORM rows use explicit declared types. An internal caller that omits a required request or template field now fails visibly instead of being treated as a disabled option or empty value. Wire formats and cache key inputs do not change.

## Verification

Ruff check and Ruff format --check passed for all four target files and the direct stream orchestrator caller. Python AST parsing passed for those five files. Caller scanning confirmed the chat route, stream orchestrator, and bootstrap runtime share the declared `ChatRequest` type; cache key resolution delegates to the `Session`-typed corpus token owner. `git diff --check` passed. Python tests were not run per user instruction.
