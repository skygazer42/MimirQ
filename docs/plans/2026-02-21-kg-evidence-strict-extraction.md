# KG Evidence-Strict Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make MimirQ's KG safe and useful for RAG by requiring chunk-local evidence spans for event->entity edges and entity->entity relation triples by default, with improved observability and regression tests.

**Architecture:** Keep the existing chunk-based extraction pipeline (events/entities first, then optional relations/skills) but enforce deterministic evidence gating during persistence. Strengthen prompts to increase evidence compliance and add metrics/tests to prevent silent graph collapse.

**Tech Stack:** FastAPI backend, SQLAlchemy ORM, Postgres for KG tables, Milvus for KG vectors, pytest for regression tests.

---

### Task 1: Make Evidence-Required Default (Config + Docs)

**Files:**
- Modify: `app/core/config.py`
- Modify: `docker/.env.example`
- Modify: `docs/guides/knowledge_graph.md` (optional, small note)

**Step 1: Write failing test**

Add a focused test asserting entities without in-text mentions are dropped when evidence is required.

File: `tests/test_kg_evidence_required_entities.py`

```python
def test_entities_without_mentions_are_dropped_when_evidence_required(...):
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_evidence_required_entities.py -v`
Expected: FAIL (current default evidence_required may be off).

**Step 3: Minimal implementation**

- Set `KG_EXTRACT_EVIDENCE_REQUIRED: bool = True` by default in `app/core/config.py`.
- Add env example lines:
  - `KG_EXTRACT_EVIDENCE_REQUIRED=true`
  - `KG_EXTRACT_ENTITY_VERIFY_ENABLED=false`
  - `KG_EXTRACT_RELATION_VERIFY_ENABLED=false`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_evidence_required_entities.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/core/config.py docker/.env.example tests/test_kg_evidence_required_entities.py
git commit -m "feat(kg): require evidence by default for entities/relations"
```

---

### Task 2: Strengthen Relation Prompt for Evidence Compliance

**Files:**
- Modify: `app/rag/kg/extraction/relation_processor.py`
- Test: `tests/test_kg_relation_processor.py`

**Step 1: Write failing test**

Add an assertion that the prompt includes explicit "verbatim substring" instructions and "must include both endpoints".

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_relation_processor.py -v`

**Step 3: Minimal implementation**

Update the prompt in `RelationProcessor.extract_relations()` to:
- explicitly state evidence_quote must be copied verbatim
- explicitly require evidence_quote to contain both subject and object surfaces
- keep constraints about candidate ids and allowlist predicates

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_relation_processor.py -v`

**Step 5: Commit**

```bash
git add app/rag/kg/extraction/relation_processor.py tests/test_kg_relation_processor.py
git commit -m "feat(kg): harden relation prompt evidence constraints"
```

---

### Task 3: Update Extraction Tests to Be Evidence-Compatible

**Files:**
- Modify: `tests/test_kg_extract_relations_integration.py`
- Modify: `tests/test_kg_extract_replace_ordering.py`
- Modify: `tests/test_kg_relation_allowlist_setting.py`
- Modify: `tests/test_kg_extract_skill_taxonomy_relations.py`
- Modify: `tests/test_kg_extract_skills_linked_to_events.py` (if needed)

**Step 1: Write failing tests (already failing)**

With evidence required default on, tests that use chunk text not containing the entity names should fail.

**Step 2: Run tests to verify failures**

Run: `pytest tests/test_kg_extract_relations_integration.py -v`
Expected: FAIL (entities dropped -> relations not extracted).

**Step 3: Minimal implementation**

Update test chunk contents to contain entity names (and relation evidence quotes where needed), e.g.:
- chunk content: `"Alice works with Bob."`
- relation extractor fake output includes `"evidence_quote": "Alice works with Bob"`

**Step 4: Run tests to verify they pass**

Run:
- `pytest tests/test_kg_extract_relations_integration.py -v`
- `pytest tests/test_kg_extract_replace_ordering.py -v`
- `pytest tests/test_kg_relation_allowlist_setting.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_kg_extract_relations_integration.py tests/test_kg_extract_replace_ordering.py tests/test_kg_relation_allowlist_setting.py tests/test_kg_extract_skill_taxonomy_relations.py tests/test_kg_extract_skills_linked_to_events.py
git commit -m "test(kg): make extraction tests compatible with strict evidence gating"
```

---

### Task 4: Add Observability Counters for Evidence Drops

**Files:**
- Modify: `app/rag/kg/extraction/extractor.py`

**Step 1: Write failing test**

Add a small unit-style test that monkeypatches extraction to produce entities not present in chunk text and asserts metrics dict includes a non-zero drop counter.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_extract_metrics_evidence_drop.py -v`

**Step 3: Minimal implementation**

In `EventExtractor.extract()`:
- Track counts for:
  - `kg_entities_total_raw`
  - `kg_entities_kept`
  - `kg_entities_dropped_no_evidence`
  - `kg_relations_total_raw`
  - `kg_relations_kept`
  - `kg_relations_dropped_no_evidence`
- Include these counts in the final `log_metrics({...})` payload.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_extract_metrics_evidence_drop.py -v`

**Step 5: Commit**

```bash
git add app/rag/kg/extraction/extractor.py tests/test_kg_extract_metrics_evidence_drop.py
git commit -m "feat(kg): add metrics for evidence drop rates"
```

---

### Task 5: Run Quality Gates + Land

**Step 1: Run unit tests**

Run: `pytest -q`
Expected: PASS.

**Step 2: Run lint (if configured)**

Run: `ruff check .`
Expected: no errors.

**Step 3: Update bd issue status / file follow-ups**

- Create follow-up issues for:
  - Skill evidence gating (optional future)
  - Persisting KG diagnostics runs (existing ready issue)

**Step 4: Pull + sync + push**

```bash
git pull --rebase
bd sync
git push
git status
```

