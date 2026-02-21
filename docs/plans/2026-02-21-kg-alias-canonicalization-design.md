# KG Alias + Canonicalization Heuristics Design

**Date:** 2026-02-21

## Goal

Improve KG extraction quality for RAG by **reducing entity fragmentation** across documents/chunks, so that:

- Query recall improves when users use abbreviations (e.g. "RAG", "THU").
- KG relation-driven expansion can safely traverse **high-signal identity edges** (`alias_of`) rather than drifting across generic relations.
- We avoid injecting noisy entities (e.g. sentence fragments) during heuristic extraction.

This work is a focused extension of the hybrid KG plan (`docs/plans/2026-02-21-kg-hybrid-graph-design.md`) with a narrow scope:
high-precision alias detection + entity canonicalization.

## Current State

- KG stores events + entities.
- Optional relation extraction persists `kg_relations` edges.
- KG search can optionally perform relation expansion, and treats `alias_of` as a high-signal predicate.

However, entity names frequently fragment due to:

- Parenthetical abbreviations: `Long Form (ABBR)`
- Chinese abbreviations: `清华大学（THU）`, `X，简称Y`
- Inconsistent surfaces across docs: `Retrieval-Augmented Generation` vs `RAG`

Without explicit alias edges and consistent entity surfaces, KG search expansion underperforms and RAG recall drops.

## Design Principles

- **Precision over recall:** only fire on explicit patterns; skip ambiguous cases.
- **Evidence-first:** only derive aliases that appear in the chunk text.
- **Anchored to extracted entities:** canonical surfaces must align to entities extracted for the chunk (avoid long context captures becoming new entities).
- **Fail-open:** if heuristics fail, extraction should still succeed.
- **Config-gated + guardrails:** caps and confidence values are settings-driven.

## Proposed Changes

### 1) Alias Heuristics Module

Introduce `app/rag/kg/extraction/alias.py` with:

- `extract_alias_candidates(text)`: detect explicit alias definitions via:
  - Parentheses: `X (Y)`
  - Chinese patterns: `X，简称Y / 又称 / 也称 / 以下简称`
  - English patterns: `X aka Y / also known as`
- `choose_alias_direction(a, b)`: decide which surface is the alias vs canonical:
  - ASCII abbreviations: prefer `alias=ABBR` (all-caps, digits, compact tokens like `GPT-4`)
  - CJK abbreviations: conservative `2-4` chars, exclude common full-name suffixes (e.g. `大学/公司/研究院/...`)
- `best_suffix_match(text, candidates)`: best-effort alignment helper when regex captures leading context
  (common in CJK without spaces).

### 2) Entity Canonicalization During Event Processing

In `app/rag/kg/extraction/extractor.py`, canonicalize extracted entity lists per chunk:

- When an extracted entity name looks like `Long (ABBR)`:
  - Expand to **two entities**: `Long` and `ABBR`
  - Only when both surfaces appear in the chunk text (evidence guard)

This increases the chance both alias/canonical surfaces exist as entities before we write `alias_of` edges.

Config:
- `KG_ENTITY_CANONICALIZE_PARENTHESES_ALIAS=true`

### 3) Heuristic Alias Edge Insertion During Relation Extraction

When relation extraction is enabled (requires `KG_RELATION_ENABLED=true` or per-request override):

For each processed chunk:

1. Extract alias candidates from chunk text.
2. Decide direction (`alias_surface`, `canonical_surface`).
3. **Anchor canonical to extracted entities**:
   - Exact normalized match, or
   - Suffix match against extracted entity normalized names (prevents creating entities like `我们使用清华大学`).
4. Ensure both sides exist as KG entities:
   - Canonical can be upserted only if anchored to extracted entities.
   - Alias may be upserted only when it looks like an abbreviation token (high precision).
5. Insert `KgRelation(predicate="alias_of")` with:
   - `confidence = KG_RELATION_ALIAS_CONFIDENCE`
   - `qualifiers = {"method": "heuristic_alias", "pattern": <pattern>}`
   - chunk/document provenance in `references`

Configs:
- `KG_RELATION_ALIAS_HEURISTIC_ENABLED=true`
- `KG_RELATION_ALIAS_MAX_CANDIDATES_PER_CHUNK=10`
- `KG_RELATION_ALIAS_CONFIDENCE=0.95`

## Why This Helps RAG

- `alias_of` edges are treated as identity-like edges during KG search expansion and can bridge
  user queries like "RAG" to events/entities written as "Retrieval-Augmented Generation".
- This improves recall without requiring aggressive synonym mining or fuzzy matching.
- The anchoring rule prevents polluting the KG with non-entities, preserving precision (critical for downstream RAG grounding).

## Testing Strategy

Unit tests in `tests/test_kg_alias_heuristics.py` cover:

- Parentheses extraction trims leading context (e.g. "We use ... (RAG)" -> "Retrieval-Augmented Generation")
- Chinese abbreviation direction selection:
  - `清华大学` vs `THU`
  - `清华大学` vs `清华`
  - `中国科学院` vs `中科院`
- Suffix alignment helper (`best_suffix_match`) prefers the longest match

## Rollout Plan

1. Enable the code paths behind existing feature flags:
   - Relations must be enabled for alias edges to be persisted.
2. Start with conservative defaults:
   - Low candidate caps per chunk
   - High confidence for heuristic edges
3. Observe:
   - KG entity growth rate
   - Relation expansion debug stats (`predicate_hist`, neighbors selected)
   - RAG retrieval metrics (answer citation quality / recall)

## Non-Goals

- Open-world synonym mining without explicit textual evidence.
- Full OpenSPG-style dynamic ontology management.
- Learning-based alias linking models (this is strictly rule + evidence driven).

## Follow-Ups

- Add metrics counters for: alias candidates extracted, alias edges inserted, candidates skipped by anchoring.
- Add a small offline eval harness for alias recall impact (ties into Dynamic OneEval-style diagnostics).

