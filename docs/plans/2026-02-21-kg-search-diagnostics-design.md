# KG Search Diagnostics: Dynamic OneEval-Style Eval Design

**Date:** 2026-02-21

## Goal

Add a **diagnostic evaluation loop** for Knowledge Graph (KG) search that:

- Samples **failed / weak** KG search queries (seeded from RAGAS regression cases).
- Generates **hard cases** (knowledge pressure + reasoning pressure), defaulting to LLM-based synthesis.
- Produces a compact, actionable **attribution report** to drive iterative improvements:
  - `vector` / `entity` / `relation` / `skill` / `extraction_missing` / `rerank_cutoff` / `other`.

This is explicitly inspired by Dynamic OneEval's "error-driven synthesis + controlled difficulty + diagnostic output"
but scoped to MimirQ's KG search pipeline.

## Non-Goals (This Iteration)

- Persisting KG diagnostic runs in DB (no new tables; result is computed-on-demand).
- A full leaderboard / benchmark system.
- Changing production KG search defaults.

## Why This Matters For RAG

MimirQ is a "giant RAG system". KG search improves RAG in two ways:

1. **Direct recall**: KG returns high-signal events/entities linked to evidence chunks.
2. **Query expansion**: KG-derived entity names can generate extra retrieval queries (`RAG_KG_QUERY_EXPANSION_ENABLED`).

But without an eval loop, KG extraction/search improvements are hard to validate and regressions are easy to miss.

## Seed / Ground Truth Strategy

We use **RAGAS regression cases** as the seed dataset because they provide **human-verified evidence pointers**:

- `ragas_regression_cases.question` is the query.
- `ragas_regression_cases.reference_sources[*].chunk_id` is evidence ground truth.

Ground truth for KG search is derived as:

- `evidence_chunk_ids = {reference_sources.chunk_id}`
- `ground_truth_event_ids = SELECT kg_source_events.id WHERE kg_source_events.chunk_id IN evidence_chunk_ids`

## Auto-Extract KG Preflight (Default: ON)

Diagnostics can fail for the wrong reason if KG extraction hasn't run for the evidence docs.

Preflight behavior (default):

- For each involved `document_id` (from `reference_sources[*].document_id`):
  - If `documents.doc_metadata.kg_extracted_at` is missing, trigger KG extraction for that document.
  - Concurrency is bounded (defaults: 2-3).
  - Extraction toggles follow settings, but can be overridden per request:
    - `extract_skills` (SkillNet-style nodes)
    - `extract_relations` (triples + taxonomy edges)

## API Surface (MVP)

Add a new API endpoint under the existing Evaluations router:

`POST /api/v1/evaluations/kg/search/diagnostics`

Request fields (proposed):

- `dataset_id: UUID` (required)
- `case_ids: list[UUID]` (optional)
- `max_cases: int` (default 50)
- `k: int` (default 10; used for Hit@K)
- `auto_extract_kg: bool` (default true)
- `extract_skills: bool | None` (override; default = settings)
- `extract_relations: bool | None` (override; default = settings)
- `hardcase_mode: "off"|"llm"|"deterministic"` (default "llm")
- `hardcases_per_failed_case: int` (default 4)
- `max_failed_cases_for_hardcase: int` (default 20)
- `llm_temperature: float` (default 0.2)

Response fields (proposed):

- `summary`: aggregate metrics + counts + preflight stats
- `items[]`: per-case diagnostics:
  - baseline run: KG search results + metrics
  - hardcases run: synthesized queries + results + metrics (when enabled)
  - attribution: primary cause + supporting signals (clues/stats/ground-truth presence)

## Metrics

For each query run:

- `hit_at_k`: any returned event has `chunk_id in evidence_chunk_ids` within top K
- `mrr`: reciprocal rank of the first evidence hit (0 if no hit)
- `recall`: fraction of evidence chunks matched by returned events (chunk-level)

Notes:
- KG search returns events with `chunk_id`, so this stays deterministic and cheap.
- If KG search returns fewer than `k` events, we evaluate on the available list.

## Hard Case Generation (Default: LLM)

Hardcases are generated only from baseline failures (bounded by `max_failed_cases_for_hardcase`).

Two categories:

1. **Knowledge pressure**
   - Term variation / alias pressure (abbreviations, alternate naming)
   - SkillNet-inspired tags/categories where available (e.g., query uses `docker` but evidence uses "Docker Compose")

2. **Reasoning pressure**
   - Multi-step constraints ("compare", "under condition X", "before/after", "trade-offs")
   - Still answerable from the same evidence sources (strict requirement)

LLM input includes:

- Original question.
- Evidence snippets from `reference_sources.quote` (or best-effort extracted chunk content; bounded).
- Optional: top ground-truth entity names derived from KG events for those chunks.

LLM output schema:

- `hardcases: [{ kind, question, rationale }]`

Guardrails:

- Deduplicate hardcases (casefold + whitespace collapse).
- Cap length.
- Ensure at least one evidence keyword/entity surface appears (best-effort).

## Attribution Heuristics (MVP)

Each failed run gets a primary cause label:

- `extraction_missing`: evidence chunks have **0** KG events after preflight.
- `vector`: KG search produced low/empty `clues` for `query->entity` and `query->event` (or no entities selected).
- `relation`: relation expansion enabled but contributes 0 edges / neighbors (see `stats.relation_expansion`).
- `skill`: Skill entities are present in evidence but KG search selected none (or skill expansion not enabled).
- `rerank_cutoff`: ground truth appears in candidates (if observable) but not in top results (limited MVP signal).
- `other`: fallback.

We keep heuristics conservative and use `kg_search` output (`entities`, `clues`, `stats`) plus ground-truth event counts.

## Security / PII

- Endpoint requires dataset read permission (same semantics as regression suite).
- Uses document ACL trimming where applicable.
- Do not persist raw query/evidence in metrics logs by default (existing `METRICS_LOG_INCLUDE_TEXT` behavior stands).
- Diagnostic response will include the regression question text (expected; regression cases are already stored text).

## Testing Plan (MVP)

- Unit tests:
  - Metrics computation (Hit@K, MRR, Recall) given synthetic KG search results.
  - Ground truth resolution from evidence chunk ids (DB fixture).
  - Hardcase JSON parsing + guardrails (LLM mocked).
- API tests:
  - Endpoint returns 200 and stable response shape.
  - ACL enforcement: cannot run on unreadable dataset.

## Rollout / Guardrails

- Feature behind `KG_ENABLED=true` (existing requirement).
- Runtime guardrails:
  - Max cases (hard cap) to avoid runaway cost.
  - Max hardcases (hard cap) to avoid runaway LLM calls.
  - Bounded extraction concurrency.

