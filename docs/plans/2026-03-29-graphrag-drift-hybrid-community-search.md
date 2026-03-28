# MimirQ-3q22 GraphRAG / DRIFT 混合全局-局部社区搜索方案

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define an incremental GraphRAG-inspired plan that adds community-level global search to MimirQ's existing KG pipeline while preserving the current local/global/drift routing semantics and evidence-backed local retrieval.

**Architecture:** Do not adopt Microsoft GraphRAG as a wholesale replacement. Instead, keep MimirQ's current KG facts, query-mode routing, and evidence injection pipeline, then add an offline community-summary layer that is used selectively for `global` and `drift` style questions.

**Tech Stack:** Python, PostgreSQL, Milvus, existing KG pipeline, community detection/summarization jobs, GraphRAG-style global search concepts

---

## Current MimirQ Baseline

Relevant repo anchors:

- `docs/guides/knowledge_graph.md`
  The repo already supports KG query-mode routing with `local`, `global`, `drift`, and `auto`.
- `app/rag/kg/pipeline.py`
  KG search is already callable as an application pipeline.
- `app/rag/retrieval/orchestrator.py`
  Current RAG can already use KG query expansion and chunk injection as optional signals.
- `app/rag/kg/search/query_mode.py`
  There is already deterministic logic for how query modes adjust recall budgets.

This is important because the issue is not "introduce global/local/drift concepts". Those concepts already exist.

The real gap is:

- MimirQ lacks a community-summary layer that makes `global` and `drift` searches more GraphRAG-like.

## Options Compared

| Option | Description | Upside | Main drawback | Recommendation |
| --- | --- | --- | --- | --- |
| A | Keep current KG routing only | Lowest risk; already live | No explicit community abstraction for global synthesis | Baseline only |
| B | Adopt Microsoft GraphRAG wholesale | Strong conceptual completeness | Large pipeline migration, duplicated infra, unclear fit with current KG model | Reject |
| C | Add an offline community-summary layer on top of current KG | Incremental, evidence-friendly, reuses current routing | Needs snapshot/build pipeline and summary governance | Recommended |

## Recommendation

Choose Option C.

The hybrid should work like this:

1. Keep current KG entity/event extraction and evidence storage unchanged.
2. Periodically build dataset-scoped or pipeline-scoped graph communities from existing KG facts.
3. Summarize each community into a compact, retrievable community summary artifact with back-pointers to underlying evidence.
4. Route queries using the existing `local/global/drift/auto` classifier:
   - `local`: current KG local path only
   - `global`: community summaries first, then local evidence backfill
   - `drift`: community summaries across snapshots or change windows first, then local evidence backfill
   - `auto`: continue to resolve into one of the above

This satisfies the issue acceptance materially because it makes `global` and `drift` more than just larger event budgets.

## Proposed Data Flow

### Existing local path

- document chunks -> events/entities/relations
- PostgreSQL stores facts and provenance
- Milvus stores KG vectors
- KG search retrieves entities/events and can inject chunks into RAG

### New community path

- batch job groups KG graph into communities
- each community produces:
  - summary text
  - representative entities
  - representative events
  - supporting evidence references
  - optional snapshot/version id
- community summaries are stored as retrievable artifacts, either:
  - pseudo-documents in the current retrieval stack, or
  - a dedicated summary table plus vector index

### Query behavior

- `local`
  - preserve current entity/event-centric evidence retrieval
- `global`
  - retrieve top community summaries
  - then fetch supporting local evidence from the winning communities
- `drift`
  - compare community summaries across two snapshots or time windows
  - then fetch local evidence showing the underlying change

## Minimum POC Boundary

The first POC should be narrow and batch-oriented:

- one dataset or tenant slice only;
- one community build job run offline;
- summary artifacts built nightly or on demand, not per request;
- no new frontend required;
- only affect `global` and `drift` queries behind a flag.

The POC should prove:

- whether community summaries materially help answer high-level or change-oriented questions;
- whether evidence backfill remains trustworthy;
- whether community refresh cadence is operationally acceptable.

Out of scope for the first POC:

- replacing the current local KG search,
- dynamic on-the-fly community generation,
- full GraphRAG ingestion pipeline replacement.

## Required Dependencies and Data

1. Community construction strategy
   A later execution issue must choose a community detection approach and keep it stable enough to compare across snapshots.

2. Summary schema
   Every community summary must preserve:
   - dataset / pipeline scope
   - build timestamp or snapshot id
   - top entities/events
   - supporting evidence pointers

3. Query battery
   Build representative `global` and `drift` questions from current product usage, not only synthetic prompts.

4. Evaluation criteria
   Measure:
   - answer usefulness on global/drift tasks,
   - evidence anchoring,
   - freshness/staleness,
   - runtime latency versus current broad-budget KG search.

## Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Summary hallucination or loss of provenance | Global summaries are dangerous without evidence links | Require summary-to-evidence back pointers |
| Community instability | Small graph changes can reshuffle communities | Snapshot and version the community build output |
| Stale global view | Batch summaries lag behind raw KG facts | Restrict use to workloads that tolerate bounded freshness |
| Redundant architecture | Could duplicate current `global` mode without real gain | Compare directly against current broad-budget KG search |
| Cost blow-up | Summary generation can become expensive | Keep it offline and dataset-scoped in v1 |

## Rollout Steps

### Phase 1: Community artifact design

- Define how community summaries are stored and cited.
- Define snapshot/version semantics for `drift`.

### Phase 2: Offline community build

- Build communities from one representative dataset.
- Generate summaries with evidence back-pointers.

### Phase 3: Retrieval integration

- Add community-summary retrieval only for `global` and `drift`.
- Keep `local` untouched.

### Phase 4: Evaluation and decision

- Compare:
  - current `global` mode,
  - hybrid `global`,
  - current `drift`,
  - hybrid `drift`.

Promote only if summaries materially improve synthesis quality without weakening explainability.

## Relationship to Graph DB Selection

This plan deliberately does not require a graph DB migration.

If later evaluation shows that community construction, traversal, or snapshot diffing becomes painful in the current stack, that becomes a concrete input into `MimirQ-om6n`. Until then, GraphRAG-style community search should be treated as a retrieval-layer enhancement, not a storage rewrite.

## What Would Justify Closing `MimirQ-3q22`

This issue can be closed once the team has:

- selected the hybrid approach over wholesale GraphRAG adoption;
- documented how `local`, `global`, and `drift` will behave after the enhancement;
- defined the minimum community-summary artifact and POC scope;
- created follow-on execution work for community build, summary storage, and retrieval evaluation.

## References

- Microsoft GraphRAG docs: `https://microsoft.github.io/graphrag/`
