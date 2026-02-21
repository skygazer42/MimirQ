# KG Evidence-Verified Extraction (Entities + Relations) Design

**Date:** 2026-02-21

## Goal

Improve KG extraction quality for the "giant RAG system" use case by addressing the four primary failure modes:

- **A) Noise (low precision):** too many low-signal entities / hallucinated relations.
- **B) Missing (low recall):** important entities/relations not extracted, especially in long chunks.
- **C) Fragmentation:** alias/canonical surfaces split the same concept across nodes.
- **D) Weak relations:** predicate drift (`unknown`) and ungrounded edges reduce usefulness for recall expansion.

The core approach is **evidence-first extraction** with **multi-pass LLM verification** plus deterministic gating:

- If an entity/relation cannot be grounded to an evidence quote inside the target chunk, it should not be persisted.
- Persist evidence (quote + span) to support debugging, attribution, and safe downstream use in RAG.

## Decision (Approved)

We will ship an **industrial-first "verified graph" default**:

- **Entities (event -> entity edges) are evidence-required by default.**
  - If we cannot ground an entity mention to a chunk-local evidence quote/span, we do not persist the edge.
  - Implementation uses deterministic gating + best-effort fallback evidence derived from the entity surface mention.
- **Relations / triples (entity -> entity edges) are evidence-required by default.**
  - If we cannot ground a relation to a chunk-local evidence quote/span (and both endpoints appear in that quote),
    we do not persist the relation.
  - Relations do NOT use fallback mention-based evidence generation (to avoid "fabricated" relations).
- **Skills remain best-effort in this iteration** (Skill nodes can be extracted without evidence gating).
  - Note: some SkillNet-style taxonomy edges are stored in `kg_relations`; they are currently treated as
    structural edges with provenance (chunk_id/content_hash) rather than strict evidence quotes.

This bias is intentional: for a RAG-first system, a noisy graph harms recall expansion and downstream answer quality
more than a smaller-but-correct graph.

## Current State

MimirQ KG is stored as **Postgres tables + Milvus vector indexes**:

- Postgres:
  - `kg_source_events` (chunk-scoped events)
  - `kg_entities` (entities; dedup by `(tenant_id, normalized_name, type)`)
  - `kg_event_entities` (event<->entity edges)
  - `kg_relations` (entity->entity edges / triples)
- Milvus:
  - `kg_events` (event vector search)
  - `kg_entities` (entity vector search)

Extraction today:

- Pass A: LLM extracts events + entities from chunk text.
- Pass B (optional): LLM extracts relations constrained to candidate entities.
- Heuristics: high-precision alias detection adds `alias_of` edges.

Limitations:

- By default, entities/relations can be persisted even when evidence quotes are missing or cannot be matched
  (unless strict mode is enabled).
- Relation extraction is constrained to an allowlist, but can still drift to `unknown` and may carry weak/unmatched evidence.
- Event extraction recall depends on `KG_EXTRACT_MAX_EVENTS_PER_CHUNK` and the chosen prompt template.

## Proposed Changes

### 1) Evidence Storage (No New Tables)

Persist evidence at the *edge* level:

1. Event -> Entity edges: store evidence in `kg_event_entities.extra_data`.
2. Entity -> Entity edges: store evidence in `kg_relations.references`.

Evidence fields:

- `evidence_quote` (string, bounded)
- `evidence_start_char` (int, best-effort)
- `evidence_end_char` (int, best-effort)

### 2) Multi-Pass Extraction (High-Quality Mode)

Per chunk, run up to 3 LLM calls (gated by settings):

1. **Candidate extraction (high recall):**
   - Extract up to `KG_EXTRACT_MAX_EVENTS_PER_CHUNK` events.
   - Extract entity candidates with an evidence quote (prefer exact substring).
2. **Entity verification + canonicalization (precision + fragmentation):**
   - Given candidate entities and target chunk text, decide keep/drop.
   - Optionally correct entity types and descriptions.
   - Optionally emit alias edges between candidates (evidence required).
3. **Relation extraction + verification (relation quality):**
   - Extract relations constrained to verified candidates.
   - Require per-relation evidence quote (sentence/phrase containing both endpoints).
   - Verify and filter relations; map predicates to allowlist.

### 3) Deterministic Evidence Gating

Even with schema-hinted JSON, the backend must gate persisted data deterministically:

- Entity evidence is accepted if:
  - `evidence_quote` matches target chunk text (exact or whitespace-flex match), or
  - the entity surface name matches target chunk text and we can synthesize a bounded quote.
- Relation evidence is accepted if:
  - `evidence_quote` matches target chunk text, and
  - both endpoint surfaces appear in the quote (best-effort).

Items that fail gating are dropped.

### 4) Safe Rollout via Settings

Add feature toggles (default off / safe-by-default):

- `KG_EXTRACT_EVIDENCE_REQUIRED` (**default true**; can be disabled for backwards-compatibility)
- `KG_EXTRACT_ENTITY_VERIFY_ENABLED` (default false)
- `KG_EXTRACT_RELATION_VERIFY_ENABLED` (default false)

Keep backwards compatibility when toggles are off.

## Testing / Eval Loop

Support both evaluation sources:

1. Existing RAGAS regression cases with human-verified `reference_sources`.
2. Auto-generated weakly-supervised cases:
   - sample chunks
   - generate question/answer from chunk
   - set that chunk as evidence (`reference_sources[{document_id, chunk_id, quote}]`)

Primary deterministic metrics:

- `Hit@K`, `MRR@K`, `Recall@K` (chunk-level, via KG diagnostics endpoint).

## Non-Goals (This Iteration)

- Full dynamic ontology editor / DB-driven predicate management.
- Multi-hop symbolic reasoning paths (OpenSPG/KAG-style solver).
- Persisting diagnostics runs (separate issue).
