# MimirQ-xwhv 跨语言检索 / 重写路由策略建议

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define a concrete cross-language retrieval and rewrite policy that improves multilingual recall while preserving named entities, code terms, and original-language evidence, without forcing an immediate reindex or a translate-everything architecture.

**Architecture:** Keep the current hybrid retrieval stack and multilingual embedding baseline, but add explicit routing around language detection, original-language-first retrieval, bounded rewrite/translation fallback, and slice-level evaluation. Promotion should happen through policy and prompt changes before any index topology changes.

**Tech Stack:** Python, FastAPI, current hybrid retriever, `bge-m3`, query rewrite strategies, multilingual regression bundles

---

## Current MimirQ Baseline

Relevant repo anchors:

- `app/rag/preprocessing/language.py`
  Current language detection is intentionally coarse: `zh`, `en`, `mixed`, `unknown`.
- `app/rag/embedding/config.py`
  `bge-m3` already exists across local and hosted providers and is a sensible multilingual dense baseline.
- `tests/test_multilingual_recall_regression.py`
  There is already a multilingual stability regression test for mixed queries and fullwidth normalization.
- `scripts/seed_public_bench_miracl_zh_pool.py`
  Public Chinese retrieval evaluation is already scriptable.
- `app/rag/core/query_rewrite_strategy.py`
  Rewrite prompts are versioned and therefore safe to iterate.
- `app/rag/retrieval/orchestrator.py`
  Rewrite, query expansion, and adaptive routing are already bounded in the main retrieval flow.

Key implication:

- MimirQ already has the minimum primitives to do multilingual routing well enough without a large architecture change.
- The missing piece is explicit policy.

## Options Compared

| Option | Description | Upside | Main drawback | Recommendation |
| --- | --- | --- | --- | --- |
| A | Translate every query into one pivot language first | Simple mental model | Loses entities and domain terms; poor for mixed-language corpora; makes lexical retrieval worse | Reject |
| B | Original-language-first retrieval with bounded rewrite/translation fallback | Best balance of relevance, safety, and incremental adoption | Needs a routing policy and more evaluation slices | Recommended |
| C | Build separate per-language indices and hard route queries | Strong isolation in theory | More indexing/ops cost; hard for mixed corpora; premature for current scale | Not first move |

## Recommendation

Adopt Option B with the following routing policy:

1. Always preserve the original query as candidate zero.
2. Detect coarse query language/script with current lightweight detector.
3. Run original-language retrieval first.
4. Only add rewritten or translated variants when the query shape or first-pass evidence suggests they are needed.
5. Track which variant won in debug metrics so the routing policy can be tuned with evidence.

This recommendation is intentionally conservative because:

- dense retrieval already has a multilingual-capable baseline,
- lexical retrieval still benefits from preserving original tokens,
- and the biggest failure mode in cross-language systems is destructive rewriting.

## Proposed Routing Policy

### Stage 1: Query classification

Classify the incoming query into one of:

- `zh`
- `en`
- `mixed`
- `unknown`

Add lightweight query traits:

- contains product tokens or code symbols
- contains bilingual terms
- follow-up / pronoun-heavy
- likely entity-heavy

### Stage 2: Original-language-first retrieval

Always run the original query first through the normal hybrid retriever.

Why:

- lexical recall is best preserved this way;
- dense multilingual embeddings can already bridge some language mismatch;
- named entities, API paths, and error strings stay intact.

### Stage 3: Bounded variant generation

Only if needed, generate a small number of additional variants:

- standalone rewrite in the same language for follow-up queries;
- script normalization or alias expansion for mixed/fullwidth cases;
- one translated query to the dominant corpus language when evidence is weak or language mismatch is likely.

Hard rules:

- never replace the original query with the translated one;
- never generate more than a small bounded variant set;
- keep code/API/product tokens verbatim where possible.

### Stage 4: Fusion and rerank

Fuse candidates across:

- original query,
- same-language rewrite,
- translated fallback if present.

The reranker should see the union, but trace metadata must record:

- which variants were generated,
- why they were generated,
- which candidate produced the winning evidence.

## Minimum POC Boundary

The first POC should not require a new index layout.

POC boundary:

- keep current embedding model family and index layout;
- add routing logic only at the query/policy layer;
- evaluate on:
  - Chinese public benchmark slice,
  - existing multilingual regression tests,
  - a small bilingual or mixed-script hard-case set;
- shadow trace the variant path before enabling on by default.

Out of scope in the first POC:

- language-specific sharded indices,
- per-language reranker fleets,
- translate-the-corpus preprocessing.

## Required Dependencies and Data

1. Evaluation slices
   At minimum:
   - `zh` public retrieval cases,
   - `en` baseline cases,
   - `mixed` and entity-heavy hard cases,
   - follow-up questions where rewrite matters.

2. Corpus language hints
   Reuse or extend document metadata language buckets from governance/profile flows for analysis and, later, optional routing hints.

3. Prompt surface
   If translation fallback is used, it needs a tightly bounded prompt or model call with explicit entity-preservation instructions.

4. Observability
   Retrieval traces should expose enough metadata to answer:
   - when fallback fired,
   - whether it helped,
   - which slice improved or regressed.

## Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Entity drift in translation | Product names, APIs, and error strings can be damaged | Preserve original query and lock protected spans |
| Hidden lexical regressions | Translation can improve dense recall but hurt keyword recall | Always run original-language retrieval first |
| Over-triggering fallback | Too many variants add latency and noise | Gate fallback on low evidence or clear mismatch signals |
| Mixed-language ambiguity | Many enterprise queries are half English and half Chinese | Treat `mixed` as a first-class slice, not a corner case |
| Lack of slice-level evidence | Improvements can be anecdotal | Report metrics by language bucket |

## Rollout Steps

### Phase 1: Policy definition and offline replay

- Freeze the routing policy.
- Run replay against multilingual regression bundles and public benchmark slices.

### Phase 2: Trace-only or shadow mode

- Generate route metadata without changing final result selection for all traffic or a small canary slice.
- Measure how often fallback would trigger.

### Phase 3: Gated enablement

- Enable same-language rewrite first.
- Enable translated fallback only for low-evidence or mismatch cases.

### Phase 4: Iterate on slices

- Review which language buckets improve.
- Decide whether index-level changes are still necessary after policy-level tuning.

## No-Go Criteria

Do not escalate to heavier architecture changes if:

- original-language-first plus bounded fallback already solves most recall gaps;
- translate-first harms lexical/entity-heavy queries;
- or there is not enough slice-level evidence to justify per-language indexing complexity.

## What Would Justify Closing `MimirQ-xwhv`

This issue can be closed once the team agrees on:

- original-language-first as the default principle;
- explicit fallback conditions for rewrite and translation;
- a bounded POC that does not require reindexing;
- slice-level evaluation criteria and trace fields for future implementation work.

## References

- BGE-M3 model card: `https://huggingface.co/BAAI/bge-m3`
- Jina embeddings v4 README: `https://huggingface.co/jinaai/jina-embeddings-v4`
