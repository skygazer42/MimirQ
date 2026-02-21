# Hybrid KG Extraction (Events + Triples + Skills) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add relation triples (`Entity-[predicate]->Entity`) and Skill/SOP nodes to MimirQ's KG, with provenance, idempotent re-extraction, and graph visualization support.

**Architecture:** Keep the existing event-centric pipeline as the backbone, then add two gated passes:
relations (persisted in a new `kg_relations` table) and skills (persisted as `kg_entities` with `type=Skill`, linked into the event graph).

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, pytest (unit tests with monkeypatch/fakes), existing LLM client abstraction (`BaseLLMClient.chat_with_schema`).

---

### Task 1: Add `kg_relations` ORM + Migration

**Files:**
- Modify: `app/rag/kg/models.py`
- Create: `alembic/versions/0002_add_kg_relations.py`

**Step 1: Add ORM model**
- Add `KgRelation` with:
  - subject/object FK to `kg_entities.id`
  - `tenant_id`, `document_id`, `chunk_id`, `event_id`
  - `predicate`, `predicate_raw`, `confidence`, `qualifiers`, `references`, `extra_data`
  - `created_at`, `updated_at`

**Step 2: Add Alembic migration**
- Create table and indexes (best-effort minimal).

**Step 3: Run import/compile sanity check**

Run:
```bash
python -m compileall -q app
```

Expected: exit code 0

**Step 4: Commit**

```bash
git add app/rag/kg/models.py alembic/versions/0002_add_kg_relations.py
git commit -m "feat(kg): add kg_relations table"
```

---

### Task 2: Make Entity Pruning Relation-Aware

**Files:**
- Modify: `app/services/indexer.py`
- Test: `tests/test_kg_prune_orphan_entities_relations.py`

**Step 1: Write failing unit test**

Create a unit test that:
- constructs an `Indexer` with a fake DB session
- ensures `prune_orphan_entities(...)` does not treat entities with relations as orphans

Implementation note: since most tests are DB-less, use a fake query object or monkeypatch the internal query to return an empty orphan set when a relation exists.

Run:
```bash
pytest tests/test_kg_prune_orphan_entities_relations.py -q
```

Expected: FAIL until implementation updated.

**Step 2: Implement prune fix**
- Update `Indexer.prune_orphan_entities` so an entity is orphan only if it has:
  - no `KgEventEntity` rows, and
  - no `KgRelation` rows where it is either subject or object.

**Step 3: Run the test**

Run:
```bash
pytest tests/test_kg_prune_orphan_entities_relations.py -q
```

Expected: PASS

**Step 4: Commit**

```bash
git add app/services/indexer.py tests/test_kg_prune_orphan_entities_relations.py
git commit -m "fix(kg): avoid pruning entities referenced by relations"
```

---

### Task 3: Add Relation Repository Helpers (Insert/Delete/Query)

**Files:**
- Modify: `app/rag/kg/repository.py`
- (Optional) Create: `app/rag/kg/relations/repository.py`
- Test: `tests/test_kg_relation_repository_contract.py`

**Step 1: Write a minimal contract test**
- Verify that:
  - `delete_relations_for_chunks(...)` calls into DB delete path
  - `list_relations_for_documents(...)` (or equivalent) returns rows in expected shape

Run:
```bash
pytest tests/test_kg_relation_repository_contract.py -q
```

Expected: FAIL

**Step 2: Implement repository**
- Provide:
  - `delete_relations_for_chunks(tenant_id, chunk_ids)`
  - `list_relations_for_documents(tenant_id, document_ids, limit)`

**Step 3: Run test**

Expected: PASS

**Step 4: Commit**

```bash
git add app/rag/kg/repository.py tests/test_kg_relation_repository_contract.py
git commit -m "feat(kg): add relation repository helpers"
```

---

### Task 4: Graph API Supports Relation Links

**Files:**
- Modify: `app/rag/kg/api/routes.py`
- Test: `tests/test_kg_graph_relation_links.py`

**Step 1: Write failing test**
- Add a unit test for `get_kg_graph`:
  - When `include_relation_links=True`, relation edges are appended to `links`
  - Edge meta includes `kind="entity_relation"` and confidence

Run:
```bash
pytest tests/test_kg_graph_relation_links.py -q
```

Expected: FAIL

**Step 2: Implement API**
- Add query param `include_relation_links: bool = False` to `get_kg_graph`
- Query `KgRelation` rows scoped to allowed documents
- Add links with `label=predicate`, `weight=confidence`

**Step 3: Run test**

Expected: PASS

**Step 4: Commit**

```bash
git add app/rag/kg/api/routes.py tests/test_kg_graph_relation_links.py
git commit -m "feat(kg): include kg_relations in graph projection"
```

---

### Task 5: Add Relation Extraction Processor (LLM -> Triples)

**Files:**
- Create: `app/rag/kg/extraction/relation_processor.py`
- Modify: `app/rag/kg/extraction/__init__.py`
- Test: `tests/test_kg_relation_processor.py`

**Step 1: Write failing tests**
- Given a candidate list of entities (with stable local ids), and a mocked LLM response:
  - output triples are parsed
  - subject/object ids must be valid candidates (invalid ones dropped)
  - predicates normalized to allowlist (unknown preserved in `predicate_raw`)

Run:
```bash
pytest tests/test_kg_relation_processor.py -q
```

Expected: FAIL

**Step 2: Implement processor**
- Use `BaseLLMClient.chat_with_schema`
- Provide schema:
  - `relations: [{subject_id, predicate, object_id, confidence, qualifiers, evidence}]`

**Step 3: Run test**

Expected: PASS

**Step 4: Commit**

```bash
git add app/rag/kg/extraction/relation_processor.py app/rag/kg/extraction/__init__.py tests/test_kg_relation_processor.py
git commit -m "feat(kg): add relation extraction processor"
```

---

### Task 6: Integrate Relation Extraction Into KG Extract (Idempotent)

**Files:**
- Modify: `app/rag/kg/extraction/extractor.py`
- Modify: `app/core/config.py`
- Test: `tests/test_kg_extract_relations_integration.py`

**Step 1: Add settings flags**
- `KG_RELATION_ENABLED` (default false)
- `KG_RELATION_MAX_RELATIONS_PER_CHUNK`

**Step 2: Write failing integration-style unit test**
- Monkeypatch LLM client to return one deterministic relation
- Monkeypatch DB session/repository to capture inserts
- Ensure:
  - when flag enabled, relation extraction is invoked
  - when `replace_existing=true`, old relations are deleted for processed chunks

Run:
```bash
pytest tests/test_kg_extract_relations_integration.py -q
```

Expected: FAIL

**Step 3: Implement integration**
- After events indexed, group entities per chunk
- Call relation processor per chunk
- Insert `KgRelation` rows with provenance (document_id/chunk_id/event_id if available)

**Step 4: Run test + commit**

```bash
git add app/rag/kg/extraction/extractor.py app/core/config.py tests/test_kg_extract_relations_integration.py
git commit -m "feat(kg): extract and persist relation triples"
```

---

### Task 7: Add Skill Extraction Processor (LLM -> Skill Cards)

**Files:**
- Create: `app/rag/kg/extraction/skill_processor.py`
- Test: `tests/test_kg_skill_processor.py`

**Step 1: Write failing tests**
- Mock LLM response -> parse skill cards
- Validate:
  - empty skills list accepted
  - `steps` coerced into list[str]

Run:
```bash
pytest tests/test_kg_skill_processor.py -q
```

Expected: FAIL

**Step 2: Implement processor**
- Schema:
  - `skills: [{name, summary, steps, inputs, outputs, tools, tags}]`

**Step 3: Run test + commit**

```bash
git add app/rag/kg/extraction/skill_processor.py tests/test_kg_skill_processor.py
git commit -m "feat(kg): add skill extraction processor"
```

---

### Task 8: Persist Skills As Entities + Link Into Event Graph

**Files:**
- Modify: `app/services/indexer.py`
- Modify: `app/rag/kg/extraction/extractor.py`
- Modify: `app/core/config.py`
- Test: `tests/test_kg_extract_skills_linked_to_events.py`

**Step 1: Add settings**
- `KG_SKILL_ENABLED` (default false)
- `KG_SKILL_MAX_SKILLS_PER_CHUNK`

**Step 2: Implement entity upsert for skills**
- Add an Indexer helper that can upsert entities (without creating events) and index entity vectors.

**Step 3: Implement skill extraction integration**
- For each processed chunk:
  - extract skills
  - upsert Skill entities + optional SkillTag entities
  - insert `KgRelation` edges for `belong_to` tags (optional in MVP)
  - insert `KgEventEntity` edges from each chunk event to each Skill entity with `role="skill"`

**Step 4: Test**

Run:
```bash
pytest tests/test_kg_extract_skills_linked_to_events.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add app/services/indexer.py app/rag/kg/extraction/extractor.py app/core/config.py tests/test_kg_extract_skills_linked_to_events.py
git commit -m "feat(kg): extract skills and link them to events"
```

---

### Task 9: Expose Extract Toggles on API Endpoint

**Files:**
- Modify: `app/rag/kg/api/routes.py`
- Test: `tests/test_kg_extract_endpoint_toggles.py`

**Step 1: Add optional query params**
- `extract_relations: bool | None`
- `extract_skills: bool | None`

**Step 2: Test**
- Ensure endpoint passes through toggles to engine/extractor config (or respects settings).

Run:
```bash
pytest tests/test_kg_extract_endpoint_toggles.py -q
```

Expected: PASS

**Step 3: Commit**

```bash
git add app/rag/kg/api/routes.py tests/test_kg_extract_endpoint_toggles.py
git commit -m "feat(kg): add extract_relations/extract_skills toggles"
```

---

### Task 10: Full Verification + Docs

**Files:**
- Modify: `docs/API.md` (optional, if API signature changes are surfaced)

**Step 1: Run quality gates**

Run:
```bash
make verify
make test
```

Expected: PASS

**Step 2: Commit plan/docs updates (if any)**

```bash
git add docs
git commit -m "docs(kg): add hybrid kg extraction notes"
```

