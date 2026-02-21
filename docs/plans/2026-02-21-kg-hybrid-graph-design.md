# Hybrid KG Extraction (Events + Triples + Skills) Design

**Date:** 2026-02-21

## Goal

Evolve MimirQ's current event-centric KG into a **hybrid knowledge graph** that supports:

- **Events** (existing): chunk-scoped "what happened" + linked entities.
- **Triples / Relations** (new): `Entity -[predicate]-> Entity` edges with evidence and confidence.
- **Skills / SOP** (new): process-oriented "know-how" as first-class nodes (plus relations) that can be searched and visualized.

This is motivated by the "structure-first" direction highlighted in OneGraph/OpenSPG/KAG/SkillNet/OneEval:
use explicit structure + provenance to improve retrieval, reasoning paths, and governance.

## Current State (Today)

MimirQ KG currently stores:

- `kg_source_events`: events extracted from document chunks.
- `kg_entities`: entities (deduped by `(tenant_id, normalized_name, type)`).
- `kg_event_entities`: event-to-entity join edges.

Extraction is chunk-based and LLM-driven (`EventExtractor`), and search is recall/expand/rerank (`KGSearcher`).

## Design Principles

- **Incremental + backwards compatible:** keep existing event extraction + search working.
- **Evidence-first:** every triple/skill should carry provenance back to chunk/event/references.
- **Constrained generation:** relations must be extracted under candidate + schema constraints to reduce hallucinations.
- **Fail-open:** if relation/skill pass fails, events extraction still succeeds.
- **Guardrails:** strict caps per chunk and per request to avoid cost and graph explosion.

## Data Model Changes

### 1) New table: `kg_relations`

Add an entity-to-entity relation table (property-graph style).

Minimal columns:

- `id` (UUID, PK)
- `tenant_id` (UUID, indexed)
- `document_id` (UUID, nullable, indexed)  
  Used for scoping + access-control filtering.
- `chunk_id` (UUID, nullable, indexed)  
  Evidence pointer.
- `event_id` (UUID, nullable, indexed)  
  Optional provenance if relation derived from a specific event.
- `subject_entity_id` (UUID, FK -> `kg_entities.id`, indexed)
- `predicate` (string, indexed)  
  Normalized predicate key (ontology-friendly).
- `predicate_raw` (string, nullable)  
  LLM raw output for debugging/governance.
- `object_entity_id` (UUID, FK -> `kg_entities.id`, indexed)
- `confidence` (numeric/float, default 0.5)
- `qualifiers` (JSON, nullable)  
  Time/location/number qualifiers to reduce "mismatch" issues (core to OpenSPG/KAG motivations).
- `references` (JSON, nullable)  
  Evidence details (`chunk_key`, `content_hash`, offsets/snippet, etc).
- `extra_data` (JSON, nullable)  
  Prompt selector, extraction strategy, future scoring fields, etc.
- `created_at`, `updated_at`

Notes:
- We store `document_id` explicitly for efficient scoping and to avoid joining through events.
- Skills use this same edge table for SkillNet-like relations.

### 2) Skills as entities (no new table)

Model skills/tags/packages as `kg_entities` rows with specific `type` values:

- `Skill`
- `SkillTag`
- `SkillPackage`

Skill "card" structure is stored in `kg_entities.extra_data`:

- `summary`, `steps`, `inputs`, `outputs`, `tools`, `preconditions`, `failure_modes`, etc.

## Extraction Pipeline Changes

Extraction becomes a multi-pass pipeline (still chunk-based):

### Pass A: Event + Entity (existing)

No breaking changes. Produces events and their entity lists.

### Pass B: Triples / Relations (new, gated)

For each processed chunk:

1. Build a candidate entity list from the chunk's extracted entities.
2. Call LLM with schema requiring relation edges referencing **candidate ids** (not free-form strings).
3. Normalize predicates against a small predicate ontology (static list v1).
4. Persist `kg_relations` edges with provenance and confidence.

Hard constraints (to reduce hallucination):
- `subject_id` and `object_id` must be from the candidate list.
- `predicate` must be from allowlist; otherwise map to `unknown` and keep `predicate_raw`.

### Pass C: Skills / SOP (new, gated)

For each processed chunk (or only when "procedural language" detected):

1. LLM extracts 0..N skills as structured objects (name + steps + I/O).
2. Persist each skill as `kg_entities` with type `Skill`.
3. Create supporting nodes/edges:
   - `Skill -> belong_to -> SkillTag` (tags)
   - `Skill -> depend_on/compose_with/similar_to -> Skill` (optional)
4. Link skills into the existing event graph by creating `kg_event_entities` edges:
   - `event -> (entity:Skill)` with `role="skill"`  
   This ensures skills appear in `GET /kg/graph` even before relation-based graph queries are added.

## Deletion / Idempotency / Pruning

When `replace_existing=true`:

- Existing behavior deletes events for processed chunks and can prune orphan entities.
- We must extend idempotency to relations/skills:
  - Delete `kg_relations` rows for the processed chunks (by `chunk_id`) before inserting new ones.
  - Update orphan pruning so entities are only pruned if they have **no**:
    - `kg_event_entities` links, and
    - `kg_relations` links (as subject or object).

This prevents accidentally deleting Skill nodes (which may not always have event links).

## API / UI Projection Changes

### `GET /kg/graph`

Add a query param:

- `include_relation_links: bool = false`

When enabled:
- Include `kg_relations` edges in `links` with:
  - `label` = predicate
  - `meta.kind = "entity_relation"`
  - `meta.confidence`, `meta.document_id`, `meta.chunk_id`, `meta.event_id` (best-effort)

Caps:
- Use existing `max_links` for total links; relations are inserted after event/entity links.

### `POST /kg/documents/{document_id}/extract`

Add optional query params (defaulting to settings):

- `extract_relations: bool | None`
- `extract_skills: bool | None`

## Settings / Feature Flags

Add safe-by-default flags:

- `KG_RELATION_ENABLED=false`
- `KG_SKILL_ENABLED=false`

And guardrails:

- `KG_RELATION_MAX_RELATIONS_PER_CHUNK` (e.g. 20)
- `KG_SKILL_MAX_SKILLS_PER_CHUNK` (e.g. 3)

## Testing Strategy (MVP)

- Unit tests for:
  - Relation parsing/normalization (predicate normalization; candidate-id mapping).
  - Orphan pruning includes relations.
  - `GET /kg/graph` includes relation links when enabled.
- Integration-style tests remain LLM-mocked (monkeypatch LLM client to deterministic JSON).

## Non-Goals (First Iteration)

- Full OpenSPG-style dynamic ontology editor UI / DB-driven ontology management.
- Relation-based search expansion (multi-hop path search) inside `KGSearcher`.
- OneEval-style full benchmark suite.

These are natural follow-ups once the storage, provenance, and extraction passes are stable.

