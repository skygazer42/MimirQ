# KG Optimization Sweep (20 Tasks)

**Date:** 2026-02-24

**Goal:** Improve KG (Knowledge Graph) safety, performance, and maintainability with a concrete 20-item checklist, implemented in one cohesive change-set.

**Non-goals:**
- Redesign KG schema or introduce new storage backends.
- Change KG ranking algorithms materially (no relevance regression risk in this sweep).
- Add large new user-facing features beyond small API hardening/ergonomics.

---

## Checklist (20 Tasks)

### A) Safety + Correctness (Scope Semantics)

1. Fix `app/rag/kg/pipeline.py` so `KG_ENABLED=false` is enforced even after the engine has been initialized (no stale cached engine bypass).
2. Add a public `reset_kg_engine()` helper in `app/rag/kg/pipeline.py` for tests and runtime toggles.
3. Make engine initialization in `app/rag/kg/pipeline.py` concurrency-safe (avoid double init under concurrent first requests).
4. Treat `document_ids=[]` as an explicit empty scope (return empty results), not as "no filter" (prevents cross-document leakage).
5. Apply the empty-scope rule consistently in `EventRepository.get_events_by_ids`.
6. Apply the empty-scope rule consistently in `EventRepository.search_events_by_entities`.
7. Apply the empty-scope rule consistently in `EventRepository.find_events_by_entities`.
8. Apply the empty-scope rule consistently in `EventRepository.search_similar_by_content` (Milvus expr must never broaden scope on empty lists).
9. Apply the empty-scope rule consistently in `RelationRepository.list_relations_for_entities`.
10. Ensure `RecallSearcher` treats `document_ids is not None` as "scoped", even when empty (so it can correctly return no results).
11. Ensure `ExpandSearcher` treats `document_ids is not None` as "scoped", even when empty (so it can correctly return no results).
12. Harden `POST /kg/search` so "no accessible documents after ACL filtering" returns empty results (not tenant-wide search).

### B) API Performance + Robustness

13. Convert KG read-only endpoints that use sync SQLAlchemy into sync FastAPI handlers (avoid blocking the event loop).
14. Add a `max_length` guard for `GET /kg/graph/search?q=...` to protect DB from pathological `ILIKE '%...%'` patterns.
15. Fix minor formatting/indentation issues in `app/rag/kg/api/routes.py` uncovered during the sweep (keep diffs minimal).
16. Add optional gzip output for `GET /kg/graph/export` to reduce payload size for large graphs.

### C) Observability

17. Add lightweight timing metrics for KG API heavy endpoints (graph/expand/stats/export) behind a feature flag.
18. Include scope + result sizes in metrics payload (docs/events/entities/links counts).

### D) Tests + Docs

19. Add unit tests covering: `KG_ENABLED` gating + `reset_kg_engine()` behavior.
20. Add unit tests covering: empty `document_ids` scope never broadens results + gzip export response basics; update KG docs to document new semantics.

