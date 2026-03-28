# MimirQ-d30w ColPali / 视觉检索通道评估计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decide whether MimirQ should add a ColPali-style document-page visual retrieval channel, and if so, define the smallest POC that materially improves scanned/image-heavy document recall without replacing the current text-first retrieval stack.

**Architecture:** Treat visual late interaction as a gated side-channel layered on top of the current RAG pipeline. Keep text retrieval, KG injection, and existing CLIP image citations as the primary baseline while evaluating whether page-level visual embeddings add measurable recall on scanned PDFs, tables, forms, and layout-heavy content.

**Tech Stack:** Python, FastAPI, PostgreSQL, Milvus, existing multimodal ingest, CLIP image index, ColPali / ColQwen2 style page retrieval models

---

## Current MimirQ Baseline

Relevant repo anchors:

- `app/services/image_embedding_index.py`
  Current multimodal retrieval indexes CLIP embeddings for image chunks only, and is explicitly optional and fail-open.
- `docs/guides/multimodal_ingest_debug.md`
  The existing multimodal story is "image/table evidence plus image citations", not "page-as-image retrieval".
- `app/rag/engine.py`
  The RAG engine already knows how to append image evidence and integrate image channel hits.
- `app/services/dataset_profile_service.py`
  Dataset profiling already surfaces `image_heavy` and scan-quality signals that can be used to target visual retrieval selectively.

Important implication:

- MimirQ already has a multimodal foothold.
- What is missing is a page-level visual document retrieval path for cases where OCR text is weak or layout matters.
- Therefore the correct first extraction is a bounded side-channel, not a platform-wide retrieval rewrite.

## Options Compared

| Option | Description | Upside | Main drawback | Recommendation |
| --- | --- | --- | --- | --- |
| A | Stay with current CLIP image chunk retrieval only | Lowest engineering cost; no new indexing stack | Weak for full-page scans, layout-heavy docs, tables/forms, and OCR-poor pages | Not enough for this issue |
| B | Add ColPali/ColQwen-style page retrieval as a gated side-channel | Best fit for scanned or visually structured documents; can coexist with current stack | New indexing/runtime cost and page-image storage/mapping work | Recommended |
| C | Replace default text retrieval with visual-first retrieval | Maximum multimodal ambition | High latency/cost, likely regressions on normal text corpora, unnecessary migration risk | Reject |

## Recommendation

Choose Option B: add a bounded ColPali/ColQwen-style page retrieval side-channel for a narrow corpus slice.

The intended behavior:

1. Keep current hybrid text retrieval as the default path.
2. Only invoke the visual page channel when at least one of these is true:
   - dataset profile indicates `pdf_scanned` or `image_heavy`;
   - the document class is known to be layout-sensitive, such as slide decks, forms, tables, or scanned manuals;
   - the text path returns low-confidence or low-evidence results on a guarded budget.
3. Fuse visual hits back into the existing evidence model as page-scoped pseudo-chunks or page evidence records.
4. Do not allow the visual channel to become the only answer source in v1; it must still map back to stable document and page identifiers with explainable citations.

## Why Not a Full Visual-First Stack

MimirQ is not starting from zero. The repo already has:

- a production retrieval path,
- image citations,
- dataset quality signals,
- bounded routing knobs,
- and evaluation infrastructure.

A full visual-first rewrite would introduce the most cost and the least certainty:

- it would force page-image generation and storage for all corpora,
- it would make latency/cost worse on text-dominant datasets,
- it would complicate evidence provenance,
- and it would not satisfy the "minimal actionable POC" bar.

## Minimum POC Boundary

The first POC should be intentionally narrow:

- Corpus:
  - 200 to 500 documents, or roughly 5,000 to 15,000 pages
  - only scanned PDFs, slide decks, tables/forms, or image-heavy technical manuals
- Retrieval scope:
  - offline evaluation first
  - optional shadow retrieval in online traffic behind a flag only after offline uplift is proven
- Storage scope:
  - index only page images, not arbitrary embedded crops or full figure libraries
- UX scope:
  - no new frontend requirement
  - reuse existing citation/evidence surfaces
- Success metric scope:
  - page recall uplift on the selected corpus slice
  - bounded latency and storage impact

Explicitly out of scope for the first POC:

- replacing BM25/vector retrieval for normal documents
- full multimodal answer generation from raw page images
- universal indexing of every page in every dataset

## Required Dependencies and Data

1. Page image generation
   Existing image citations are chunk/image-centric; the POC needs stable document page renders for retrieval.

2. Gold query set
   A small but high-quality evaluation slice should be built from image-heavy or scanned corpora, with relevant page-level or document-level judgments.

3. Compute budget
   A batch-oriented GPU runner is strongly preferred for visual page indexing; CPU-only indexing should be treated as fallback, not default.

4. Mapping contract
   Every visual hit must map back to:
   - `tenant_id`
   - `dataset_id`
   - `document_id`
   - `page_number`
   - a stable evidence key that the current RAG path can cite

## Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Visual index cost | Page-level embeddings can multiply storage and indexing time | Limit to targeted datasets and cap POC page count |
| Citation mismatch | A high-scoring page is useless if it cannot map back to evidence | Define page evidence schema before index build |
| Latency blow-up | Late interaction models can be expensive online | Keep v1 offline or shadow-only; use retrieval budget guardrails |
| Weak benefit on OCR-good corpora | Many corpora will not need visual search | Gate by dataset profile and query shape |
| Security / tenancy leakage | Page image assets are sensitive like documents | Reuse existing tenant-scoped document/page ownership model |

## Rollout Steps

### Phase 1: Offline corpus and metrics

- Build a small evaluation slice of scanned/image-heavy documents.
- Define metrics:
  - Recall@K on target documents/pages
  - first-relevant-page hit rate
  - storage per 1,000 pages
  - p95 retrieval latency in shadow mode

### Phase 2: Visual page index prototype

- Rasterize selected pages.
- Build a page-level visual retrieval index.
- Convert top visual hits into page-scoped evidence payloads that current fusion code can consume.

### Phase 3: Shadow fusion

- Run visual retrieval only when gating conditions trigger.
- Compare:
  - text-only
  - text + visual
- Keep promotion criteria numerical, not anecdotal.

### Phase 4: Promotion decision

Promote only if all of the following are true:

- meaningful recall improvement on image-heavy slice,
- no material regression on latency budget,
- citation mapping remains stable,
- operational cost is acceptable for targeted datasets.

## No-Go Criteria

Do not continue past the POC if:

- recall uplift is marginal relative to current CLIP + text stack,
- page evidence mapping is unreliable,
- runtime cost requires making visual indexing universal just to get small gains,
- or the model only helps on a tiny benchmark but not on real MimirQ corpora.

## What Would Justify Closing `MimirQ-d30w`

This issue can be closed once the team agrees on all of the following:

- the chosen direction is "bounded visual side-channel", not "replace main retrieval";
- the doc names the specific corpus slice and gating conditions to test first;
- metrics and no-go criteria are explicit;
- follow-on implementation can be split into execution tickets for:
  - page rendering/indexing,
  - visual hit to citation mapping,
  - offline/shadow evaluation.

## References

- ColPali model card: `https://huggingface.co/vidore/colpali-v1.3`
- ColQwen2 model docs: `https://huggingface.co/docs/transformers/model_doc/colqwen2`
