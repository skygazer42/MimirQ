# RAG Optimization Guide

This guide summarizes the most impactful knobs for improving retrieval quality and answer grounding in MimirQ.

> All settings are defined in `app/core/config.py` and can be set via `.env`.

## Recommended Order (Do This First)

When optimizing quality, follow this order to avoid “tuning noise”:

1) **Ingestion quality**: parsing + governance + chunking (use Chunk Preview).
2) **Recall**: retrieval top-k / thresholds, then hybrid fusion (BM25 + vector).
3) **Precision**: reranking (prefer deterministic providers before LLM rerank).
4) **Query enhancements**: rewrite / multi-query / HyDE / decomposition (one-by-one).
5) **Grounding**: visible-evidence-only + claim checks (reduce hallucinations).
6) **Measure & gate**: RAGAS + Evidence regression suites + CI gates.
7) **Explainability**: trace replay + metrics + export artifacts.

Key companion guides:
- Platform design principles: `docs/guides/rag_platform_design_principles.md`
- Chunking: `docs/guides/chunk_preview.md`, `docs/guides/chunk_strategies.md`
- Hybrid fusion: `docs/guides/retrieval_fusion.md`
- Reranking: `docs/guides/reranking_colbert.md`, `docs/guides/reranking_ltr.md`
- Evidence API: `docs/guides/evidence_api.md`
- Regression gate: `docs/guides/regression_gate.md`
- Evaluation maturity model: `docs/guides/evaluation_maturity_model.md`
- Knowledge Graph (optional): `docs/guides/knowledge_graph.md`

## 1) Chunking (Ingestion Quality)

Key settings:
- `CHUNK_SIZE`
- `CHUNK_OVERLAP`

Rules of thumb:
- Increase `CHUNK_SIZE` when chunks are too fragmented (too many partial matches).
- Increase `CHUNK_OVERLAP` when important context is split across chunk boundaries.
- Avoid `CHUNK_OVERLAP >= CHUNK_SIZE` (rejected by config validation).

Use the **Chunk Preview** UI to visualize and iterate:
- Guide: `docs/guides/chunk_preview.md`
- Strategies: `docs/guides/chunk_strategies.md`

## 2) Retrieval (Recall vs Precision)

Key settings:
- `RETRIEVAL_TOP_K` (how many chunks to retrieve)
- `SIMILARITY_THRESHOLD` (filter low-similarity chunks)

Typical tuning:
- If answers miss relevant facts: increase `RETRIEVAL_TOP_K` and/or lower `SIMILARITY_THRESHOLD`.
- If answers include irrelevant context: decrease `RETRIEVAL_TOP_K` and/or raise `SIMILARITY_THRESHOLD`.

## 3) Hybrid Retrieval (Vector + BM25)

Key settings:
- `BM25_INDEX_ENABLED` (enable keyword index)
- `RETRIEVAL_FUSION_STRATEGY` (`linear` or `rrf`)

When to use:
- Use BM25 for exact entity/keyword matching and for long technical documents.
- Use vector retrieval for semantic matching and paraphrased questions.
- Use `rrf` fusion when you want a robust ranking that combines both sources.

## 3.5) Sparse Retrieval (Optional)

MimirQ supports an additional **sparse** candidate source (SPLADE-style scaffolding) that can improve recall on:
- acronyms (`k8s` vs `kubernetes`)
- domain synonyms / abbreviations

Key settings:
- `SPARSE_RETRIEVAL_ENABLED`
- `SPARSE_RETRIEVAL_PROVIDER` (currently `deterministic`)
- `SPARSE_RETRIEVAL_SYNONYMS`

Guide:
- `docs/guides/sparse_retrieval.md`

## 4) Reranking

Key settings:
- `RERANKER_PROVIDER` (`llm` | `pc` | `colbert` | `ltr` | `openai` | `dashscope` | `none`)

Tradeoffs:
- `llm` rerank improves precision but increases latency/cost.
- `colbert`/`ltr` are intended for deterministic/fast reranking (local providers; see guides below).
- `none` is fastest; rely on better chunking + retrieval thresholds.

Guides:
- `docs/guides/reranking_colbert.md`
- `docs/guides/reranking_ltr.md`

## 5) Query Enhancements (Optional)

These are off by default and can improve recall on ambiguous or short queries:
- `ENABLE_QUERY_REWRITE` (rewrite follow-ups into standalone queries)
  - `QUERY_REWRITE_STRATEGY` (versioned rewrite strategy id, e.g. `kb_followup.v1`; used for evaluation gating/rollback)
- `ENABLE_MULTI_QUERY` (generate multiple query variants for recall)
- `ENABLE_HYDE` (generate a hypothetical passage to improve vector recall)
- `ENABLE_QUERY_DECOMPOSITION` (split complex questions into sub-questions)

Recommendation:
- Enable one at a time, measure impact with RAGAS/regression suites before enabling multiple.

## 5.2) RAG Config Template Adaptive Routing (AB)

Wave B 在 `rag_config_template_resolver` 增加了可选的 adaptive epsilon-greedy 路由能力（默认仍是 `weighted`，保持兼容）。

核心语义：
- `routing_mode=weighted`：按 `ab_weight` 稳定分流。
- `routing_mode=adaptive`：`epsilon` 概率探索，`1-epsilon` 概率利用历史 reward 更高的 variant。
- `feedback_reward_snapshot` / `feedback_reward_hook`：把反馈聚合结果作为利用阶段的依据。

可审计输出：
- chat/rag metrics 中 `rag_config_template.resolver_debug` 会记录：
  - `strategy`
  - `epsilon`
  - `decision`（`explore` / `exploit` / `weighted`）
  - `chosen_variant`
  - `reward_snapshot`

建议 rollout：
1. 先用 `weighted` 收集稳定反馈。
2. 再小流量启用 `adaptive`，并从 `epsilon=0.05~0.1` 起步。
3. 持续观察 `resolver_debug.decision` 与线上效果，防止 reward 偏差放大。

## 5.5) Strict Grounding (Visible Evidence Only)

If you want to strongly reduce hallucinations (at the cost of more refusals and potentially buffered streaming),
enable **visible-evidence-only** mode:

- Per-request (recommended for QA/critical workflows):
  - `rag_config.visible_evidence_only=true`
- Per-dataset default:
  - set dataset `rag_defaults.visible_evidence_only=true`

When enabled, MimirQ will:
- **Abstain early** when evidence is weak/empty (instead of "best effort" guessing)
- **Post-check generated claims** against the retrieved evidence and drop unsupported ones
- Apply the same scrubbing to **structured_output** JSON (keeps JSON parseable)

Claim verifier diagnostics now expose machine-readable removal reasons:

- `reason_code`
  - `supported`
  - `overlap_insufficient`
  - `contradiction_numeric_mismatch`
  - `contradiction_negation_conflict`
  - `nli_entailment` / `nli_contradiction` / `nli_neutral` when optional NLI fallback is enabled
- `contradiction_type`
  - `numeric_mismatch`
  - `negation_conflict`
  - `numeric_and_negation`

Operationally:

1. Keep `RAG_CLAIM_VERIFIER_MODE=token_overlap` as the cheapest baseline.
2. Move to `semantic_heuristic` when you need better numeric/negation protection.
3. Use `strict` only when evidence spans and parser quality are already stable.
4. Enable `RAG_CLAIM_NLI_VERIFIER_ENABLED=true` only as a bounded fallback layer after heuristic failure, not as the primary verifier.

### grounded_strict Profile (Recommended Rollout Baseline)

Wave D adds a strict grounding retrieval profile:

- `rag_config.retrieval_profile=grounded_strict`

`grounded_strict` applies the following contract together:

- `retrieval_mode=hybrid`
- `top_k>=20`
- `enable_reranker=true`; the provider follows the deployment's `RERANKER_PROVIDER` and falls back to `cross_encoder`
- `retrieval_contract_mode=evidence_strict`
- `visible_evidence_only=true`

Rollout recommendation:

1. Start with one dataset that has stable citations and good parse quality.
2. Observe `abstain_rate`, `claim_check_removed`, and `evidence_span_missing_citations` for 24-48 hours.
3. If refusal rate spikes because of span gaps, prioritize parser/chunking remediation before expanding rollout.
4. Keep a rollback switch by reverting dataset default to `hybrid_ce` (or clearing `retrieval_profile`).

## 6) Evaluation (Measure, Don’t Guess)

MimirQ includes RAGAS evaluation and regression helpers. See:
- `docs/guides/regression_gate.md`

## 7) Metadata Filtering (Scope + Precision)

You can restrict retrieval using `metadata_filter` (chat request `rag_config.metadata_filter`).

Use cases:
- Filter by page ranges (`page >= 10`)
- Filter by document/user tags (`document_user.tags in [...]`)
- Filter by frontmatter fields (`document_frontmatter.author contains "alice"`)

Examples:

```json
{
  "page": { "$gte": 10, "$lte": 20 },
  "document_user.tags": { "$in": ["it", "hr"] }
}
```

Notes:
- Filter keys support dotted paths (e.g. `document_user.tags`).
- Operators are fail-closed: unknown operators will not match.

## 8) Observability (Replay What Happened)

When debugging quality issues, prefer using the trace/metrics pipeline instead of ad-hoc prints.

Key settings:
- `ENABLE_METRICS_LOG=true`
- `METRICS_LOG_PATH=./logs/rag_metrics.jsonl`
- `METRICS_LOG_INCLUDE_TEXT=false` (recommended: keeps correlation hashes instead of raw question/query)

Common workflow:
1) Reproduce the bad answer
2) Inspect the RAG trace (History/Graph UI) to see retrieval mode, timings, citations and refusal reasons
3) If needed: export feedback → regression case, then gate future changes with the regression suite
