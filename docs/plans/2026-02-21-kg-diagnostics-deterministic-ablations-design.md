# KG Search Diagnostics: Deterministic Hardcases + Attribution Ablations (Design)

**Date:** 2026-02-21

## Goal

Extend the existing KG diagnostics endpoint:

`POST /api/v1/evaluations/kg/search/diagnostics`

to improve **debuggability** and **iteration velocity** for KG extraction/search quality.

This is a follow-up to the MVP diagnostics design and focuses on:

1. `hardcase_mode=deterministic` (no LLM) using KG entities/aliases/tags.
2. Attribution "ablations" to better classify failures as:
   - `vector` / `entity` / `relation` / `skill` / `rerank_cutoff` / `extraction_missing` / `other`

## Non-Goals

- Persisting diagnostics runs in DB (optional later).
- Changing production KG search defaults (all new toggles are per-call overrides; defaults remain settings-driven).

## Deterministic Hardcases

### When Generated

For each baseline failure (Hit@K=false) with non-empty ground truth events:

- Generate up to `hardcases_per_failed_case` deterministic hardcases.
- Only for up to `max_failed_cases_for_hardcase` failed cases.
- No LLM calls; fully deterministic.

### Inputs (All Local / KG-Derived)

- Ground truth evidence: `reference_sources[*].chunk_id`
- Ground truth events: `kg_source_events.id where chunk_id in evidence_chunk_ids`
- Ground truth entities: `kg_event_entities -> kg_entities` for those events
- Alias edges: `kg_relations` predicates in `("alias_of", "same_as")`
- Skill edges:
  - Skill entities linked to events: `kg_entities.type == "Skill"`
  - Tag/category neighbors via `kg_relations.predicate == "belong_to"` to `SkillTag` / `SkillCategory`

### Output Mix (User Approved)

Mixed mode, per failed case (default `hardcases_per_failed_case=4`):

- 2 alias/normalization hardcases
- 2 skill/tag hardcases

For other `hardcases_per_failed_case`, use a stable split:

- `alias_quota = hardcases_per_failed_case // 2`
- `skill_quota = hardcases_per_failed_case - alias_quota`

If one side lacks candidates, spill over to the other side.

### Hardcase Templates

All deterministic hardcases are `kind="knowledge_pressure"`:

- Alias hardcases:
  - Prefer substituting an entity surface in the original question using `alias_of` pairs.
  - Fallback: short template using the alias term only (English vs Chinese decided by presence of CJK chars).
- Skill hardcases:
  - Prefer skill name queries ("How to <skill>?" / "<skill> 步骤是什么？").
  - Optionally include 1-2 tags/categories from `belong_to` edges.

### Determinism Guardrails

- Stable sorting (confidence desc, then name asc).
- Dedupe hardcase questions by (casefold + collapsed whitespace).
- Length cap (e.g. 350 chars).

## Attribution Ablations

### Problem

Heuristic attribution alone can misclassify failures. Example:

- Baseline miss might be due to rerank strategy rather than vector recall.
- Relation expansion might help, but is disabled by default.
- Skill nodes might help or might introduce drift.

### Approach

For each baseline failure with ground truth present, run a bounded set of **extra searches**
and compare Hit@K / MRR / Recall:

1. Relation expansion toggle: flip enabled/disabled.
2. Skill nodes toggle: exclude Skill-like entities from recall/expand.
3. Rerank strategy toggle: `PAGERANK <-> RRF`.

Hard cap: at most 3 extra searches per failed case.

### Required Per-Call Overrides (Thread-Safe)

Add internal knobs to `SearchConfig` (default keeps current behavior):

- `relation_expansion_enabled: bool | None`
  - `None`: current behavior (settings-gated)
  - `True/False`: force on/off for this call (used by diagnostics only)
- `include_skill_entities: bool`
  - Default `True`
  - When `False`, filter out `Skill` / `SkillTag` / `SkillCategory` in recall + expand stages

### Attribution Decision (Overrides Heuristics)

If an ablation converts a baseline miss into Hit@K=true, set primary cause accordingly:

- rerank toggle fixes => `rerank_cutoff`
- relation toggle fixes => `relation`
- skills_off fixes => `skill` (signals indicate "skill drift/noise" style failure)

If none fix, fall back to existing heuristic attribution.

### Output

Do not change the public response schema.

Store ablation summaries in:

`item.attribution.signals["ablations"]`

Only include compact fields (hit_at_k, mrr, recall, first_hit_rank, selected_entities, returned_events, and relation debug stats).

## Testing

- Unit tests for deterministic hardcase generator:
  - stable split (2+2), dedupe, cap, deterministic ordering
- Search tests for override toggles:
  - relation expansion respects `SearchConfig.relation_expansion_enabled`
  - skill filtering respects `SearchConfig.include_skill_entities`

