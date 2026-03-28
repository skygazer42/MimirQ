# Backend Research Docs Overview

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land a docs-only decision package for six backend research issues so each issue can be closed against concrete recommendations, risks, dependencies, rollout steps, and bounded POC definitions.

**Architecture:** Keep all recommendations additive to the current MimirQ architecture unless an issue explicitly justifies deeper change. Reuse existing building blocks already present in the repo: Postgres + Milvus retrieval, KG query-mode routing, multilingual regression suites, dataset profiling, and connector-run semantics.

**Tech Stack:** Markdown, Python backend, FastAPI, PostgreSQL, Milvus, existing RAG/KG pipeline, existing connector framework

---

## Scope

This document ties together the following research outputs:

- `MimirQ-d30w`: ColPali / visual-first retrieval channel evaluation
- `MimirQ-om6n`: graph database selection evaluation
- `MimirQ-w1wo`: DSPy / prompt optimization workflow
- `MimirQ-xwhv`: cross-language retrieval and rewrite routing strategy
- `MimirQ-3q22`: GraphRAG / DRIFT hybrid global-local community search plan
- `MimirQ-nk9e`: connector roadmap for Notion / SharePoint / chat-native sources

Related plan docs:

- `docs/plans/2026-03-29-colpali-visual-retrieval-evaluation.md`
- `docs/plans/2026-03-29-graph-db-selection-evaluation.md`
- `docs/plans/2026-03-29-dspy-prompt-optimization-workflow.md`
- `docs/plans/2026-03-29-cross-language-retrieval-routing.md`
- `docs/plans/2026-03-29-graphrag-drift-hybrid-community-search.md`
- `docs/plans/2026-03-29-connectors-notion-sharepoint-chat-roadmap.md`

## Current MimirQ Baseline

The recommendations in this batch deliberately start from the current repository state:

- Retrieval and RAG already have bounded query rewrite, adaptive router flags, hybrid retrieval, and offline ablation hooks.
- KG already supports deterministic `local | global | drift | auto` query-mode routing and stores facts in PostgreSQL with vector recall in Milvus.
- Multimodal retrieval already has an optional CLIP image channel and image citations, but not a document-page visual late-interaction stack.
- Public Chinese retrieval benchmark seeding and multilingual regression slices already exist, which makes offline evaluation practical.
- Connector ingestion already has a stable registry/run/config/state contract for document-like sources, but no native Notion, SharePoint, Slack, or Teams connectors.

## Portfolio-Level Principles

Across all six issues, the same engineering constraints show up repeatedly:

1. Keep the current online path stable first.
   Prefer offline evaluation, shadow channels, or read-side replicas before changing the default request path.

2. Reuse existing evidence and regression assets.
   Use `mimirq.regression_cases.v1`, dataset profile slices, retrieval traces, and KG metrics rather than inventing new evaluation systems first.

3. Avoid forcing platform migrations before bottlenecks are proven.
   The repo already has real infrastructure in place. Most research topics can be validated as bounded POCs without changing the source-of-truth storage model.

4. Close issues against explicit POC boundaries, not aspirational architecture.
   Each issue should end with a "what we will build first" decision and "what we are intentionally not building yet" statement.

## Recommended Execution Order

The issues are not equally coupled. Recommended sequence:

1. `MimirQ-xwhv`
   Cross-language routing affects retrieval quality broadly and can reuse existing multilingual benchmark assets immediately.

2. `MimirQ-w1wo`
   DSPy should optimize existing prompts offline, after the multilingual routing slices are clear but before new online prompt variants are promoted.

3. `MimirQ-3q22`
   GraphRAG/DRIFT can build on the current KG `local/global/drift/auto` scaffolding without waiting for a graph DB migration.

4. `MimirQ-d30w`
   Visual retrieval should be validated as a bounded side-channel on image-heavy or scanned corpora, not as a default replacement.

5. `MimirQ-nk9e`
   Connector roadmap can proceed in parallel as docs work, but implementation should prioritize document-like sources before chat-native sources.

6. `MimirQ-om6n`
   Graph DB selection should stay decision-oriented until the hybrid KG/community search path proves where Postgres + Milvus becomes insufficient.

## Issue-to-Deliverable Matrix

| Issue | Current repo anchor | Recommended first deliverable | What counts as "enough to close the issue" |
| --- | --- | --- | --- |
| `MimirQ-d30w` | CLIP image retrieval, image citations, image-heavy dataset hints | Bounded ColPali/ColQwen page-retrieval side-channel POC definition | Clear decision to test visual late interaction as a gated side-channel, with metrics, corpus boundary, and no-go criteria |
| `MimirQ-om6n` | KG facts in Postgres, vectors in Milvus, query-mode routing already live | Decision memo ranking Neo4j / NebulaGraph / JanusGraph vs "stay current" | Named recommendation, why not the rejected options, and a read-side POC boundary instead of a full migration |
| `MimirQ-w1wo` | Versioned query rewrite strategies, retrieval regression artifacts, adaptive router hooks | Offline DSPy optimization workflow for prompt candidates | Workflow doc that defines inputs, metrics, promotion gate, and first prompt family to optimize |
| `MimirQ-xwhv` | Language bucket helpers, `bge-m3`, multilingual recall regression tests | Original-language-first routing policy with bounded rewrite/translation fallback | A concrete routing policy, evaluation slices, and rollout order that does not require immediate reindexing |
| `MimirQ-3q22` | Existing KG `local/global/drift/auto`, query expansion, chunk injection | Community-summary read path layered onto current KG | Hybrid design with local/global/drift behavior, community build loop, and minimum dataset-scale POC |
| `MimirQ-nk9e` | Connector registry/run semantics, ACL inheritance docs, export cleanup rules | Sequenced roadmap for Notion, SharePoint, Slack, Teams | Ordered connector plan with auth/ACL/delta assumptions and scoped POC definitions per source |

## Shared Verification Expectations

Because this batch is docs-only, the verification bar is correspondingly focused:

- Confirm only `docs/plans/` files changed.
- Run `git diff --check` to catch malformed Markdown diffs or trailing whitespace.
- Run `git status --short` from the clean worktree to ensure there are no unexpected untracked artifacts.
- Manually inspect that each issue doc includes:
  - option comparison
  - recommendation
  - risks
  - dependencies and required data
  - rollout steps
  - minimum POC boundary
  - issue close criteria

## Issue Close Guidance

These issues should be closed as "research/design complete" only when the team agrees that:

- the recommended path is specific enough to start implementation without reopening discovery;
- the POC scope is intentionally minimal and measurable;
- the rejected options are documented clearly enough to avoid re-litigating the same decision in the next session;
- any follow-on implementation work can be filed as new execution issues rather than extending the research issue indefinitely.
