# Task 19: KG Provenance + Rollback Safety

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure KG extraction outputs are traceable back to original chunks/spans (chunk_id + offsets), and that KG updates are rollback-safe (do not delete old KG until new KG is persisted).

**Architecture:** Reuse existing KG tables (`kg_source_events`, `kg_entities`, `kg_event_entities`) and existing extraction flow. Add provenance to **event-entity edges** via `KgEventEntity.extra_data` (source chunk_id/page/start_char/end_char/etc), expose it through API responses and graph projections, and add a unit test that enforces “insert-then-delete” ordering for rollback safety.

**Tech Stack:** Python, FastAPI, SQLAlchemy, existing KG extraction (`app/rag/kg/extraction/extractor.py`) and persistence (`app/services/indexer.py`).

**Status:** DONE (2026-02-06)

## Notes / Scope Choices

- **Entity provenance:** entities are global/deduped; per-occurrence provenance belongs on the **edge** (`kg_event_entities`) and can be traced via `event_id -> chunk_id` as well.
- **Rollback meaning (in-scope):** rollback-safe updates within extraction runs (persist new events first, then delete old). “Multi-version KG time travel” is out-of-scope for this task.

## Task 1: Persist edge provenance on `KgEventEntity.extra_data`

**Files:**
- Modify: `app/services/indexer.py`
- Test: `tests/test_kg_event_entity_provenance.py`

**Step 1: Write failing tests**

- Create a small pure helper (or test via monkeypatched Indexer) that builds a safe provenance dict from an event’s references.
- Required keys (when present): `document_id`, `chunk_id`, `chunk_index`, `page`, `start_char`, `end_char`, `chunk_key`, `content_hash`, `content_len`, `source`.
- Ensure values are JSON-serializable and bounded.

**Step 2: Implement minimal persistence**

- In `Indexer.index_events(...)`, when creating `KgEventEntity(...)`, set `extra_data` to the provenance dict derived from the owning event (same for all entities of that event).
- Keep schema stable: do not add DB columns.

**Step 3: Run**

Run: `python -m pytest -q tests/test_kg_event_entity_provenance.py`

## Task 2: Expose provenance in KG APIs (event detail + graph)

**Files:**
- Modify: `app/rag/kg/schemas.py`
- Modify: `app/rag/kg/api/routes.py`
- Test: `tests/test_kg_new_endpoints.py`

**Step 1: Write failing tests**

- `GET /kg/events/{event_id}` response includes `entities[].extra_data` containing `chunk_id` and `start_char/end_char` when available.
- `GET /kg/graph` links for `kind=event_entity` include provenance fields in `meta` (bounded).

**Step 2: Implement**

- Add `extra_data: Dict[str, Any]` to `KGEventEntityItem` (coerce `None -> {}`).
- In `get_kg_event_detail`, set `extra_data` from `KgEventEntity.extra_data`.
- In `get_kg_graph` (and `/graph/expand`), include safe provenance fields on `links[].meta` for `event_entity` edges.

**Step 3: Run**

Run: `python -m pytest -q tests/test_kg_new_endpoints.py`

## Task 3: Enforce rollback-safe ordering in extraction (unit test)

**Files:**
- Test: `tests/test_kg_extract_replace_ordering.py`

**Step 1: Write failing test**

- When `replace_existing=True` and new events exist:
  - `Indexer.upsert(...)` is called before `Indexer.delete_event_indexes_for_chunks(...)`.
- When `Indexer.upsert(...)` raises:
  - `delete_event_indexes_for_chunks(...)` is not called.

**Step 2: Implement (only if needed)**

- If current code already satisfies ordering, keep production code unchanged; only land the regression test.

**Step 3: Run**

Run: `python -m pytest -q tests/test_kg_extract_replace_ordering.py`

## Verify

Run:
- `python -m pytest -q`
