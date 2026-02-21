# KG Skills: SkillNet-Style Taxonomy + Relations Design

**Date:** 2026-02-21

## Goal

Improve KG-backed RAG recall for procedural/know-how queries by modeling SkillNet-style structure:

- Skills as first-class entities (`type=Skill`).
- Taxonomy nodes:
  - `SkillTag` (fine-grained labels like `python`, `docker`, `frontend`)
  - `SkillCategory` (coarse labels like `Development`, `Data`, `AIGC`)
- Relations persisted in `kg_relations` with provenance:
  - `Skill -[belong_to]-> SkillTag`
  - `Skill -[belong_to]-> SkillCategory`
  - `Skill -[compose_with]-> Skill` (within-chunk composability)

This structure enables KG search relation expansion to bridge:
`query -> SkillTag -> Skill -> Event -> Chunk` and improves recall without aggressive synonym mining.

## Constraints / Principles

- **High precision:** only use LLM-provided tags/categories from the skill extractor; do not auto-invent taxonomy.
- **Provenance-first:** every edge has chunk/document scope (`chunk_id`, `document_id`, `references`) and prompt selector metadata.
- **Bounded growth:** cap tags per skill (default 10) and skills per chunk (existing cap).
- **Backwards compatible:** existing skill extraction + event linking works even when relations are disabled.

## Data Model

No new tables:

- Taxonomy nodes are stored in `kg_entities`:
  - `type=SkillTag`
  - `type=SkillCategory`
- Edges are stored in `kg_relations`:
  - `predicate=belong_to`
  - `predicate=compose_with`

## Extraction Pipeline Changes

Extends the existing skill extraction pass in `EventExtractor`:

1. **Skill extraction (existing):**
   - LLM extracts `skills[]` with `name`, `summary`, `steps`, `inputs`, `outputs`, `tools`, `tags`, `confidence`
   - Add optional `category` field.
2. **Persist Skill entities (existing):**
   - Upsert `Skill` entities to `kg_entities` (vector embedded).
   - Link newly created events to skills via `kg_event_entities` (`role="skill"`).
3. **Persist taxonomy nodes (new, gated by relations enabled):**
   - Upsert `SkillTag` and `SkillCategory` entities (vector embedded; best-effort).
4. **Persist taxonomy relations (new, gated by relations enabled):**
   - `Skill -[belong_to]-> SkillTag/SkillCategory` with `confidence ~= skill_confidence`
   - `Skill -[compose_with]-> Skill` for co-extracted skills in the same chunk (bounded by `max_skills_per_chunk`)
   - Qualifiers include `{"method":"skill_taxonomy", "kind":"tag|category|compose_with"}`

## KG Search Impact

KG search relation expansion uses predicate weighting priors. Add priors for:

- `belong_to` (reverse direction emphasized: tag/category -> skill)
- `compose_with` (symmetric, moderate weight)

This allows queries like `"docker"` to retrieve `SkillTag("docker")`, expand to `Skill("Use Docker Compose")`,
then retrieve events linked to that skill.

## Testing

- Unit test: `SkillProcessor` passes through optional `category`.
- Integration-style unit test: extraction persists `belong_to` + `compose_with` edges when both skills and relations are enabled.

## Non-Goals (This Iteration)

- Global cross-document skill-skill relation mining.
- Skill packages (`SkillPackage`) and `packaged_in` edges.
- Full SkillNet evaluation harness (covered by separate Dynamic OneEval-style diagnostics work).

