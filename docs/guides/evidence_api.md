# Evidence API (Retrieval-Only)

This guide documents the **retrieval-only** endpoint intended for “evidence discovery”:

- No LLM answer generation
- Returns **evidence chunks** (`citations`) plus guardrail signals
- Designed for downstream systems that want to answer: **“Do we have evidence for this question in the corpus?”**

## Endpoint

`POST /api/v1/rag/retrieve`

Related:
- Dataset-scoped training export: `docs/guides/training_export.md`

### Request (JSON)

```json
{
  "query": "What is the refund policy for annual plans?",
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ],
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "document_ids": [],
  "rag_config": {
    "retrieval_profile": "recall50",
    "retrieval_mode": "hybrid",
    "top_k": 50,
    "score_threshold": 0.0
  }
}
```

Notes:
- If `rag_config` is omitted, the server defaults to **`retrieval_profile=recall50`** (recall-first).
- Prefer `dataset_id` scoping when possible (more scalable than enumerating `document_ids`).
- For multi-channel fusion tuning, you can override `rag_config.fusion_strategy` (and optionally `fusion_budgets` / `fusion_min_scores` for `budgeted_rrf`).
  See: `docs/guides/retrieval_fusion.md`.

## Response

```json
{
  "schema": "mimirq.evidence.v1",
  "query_for_retrieval": "refund policy annual plan",
  "citations": [
    {
      "document_id": "...",
      "chunk_id": "...",
      "chunk_content": "...",
      "relevance_score": 0.83
    }
  ],
  "metrics": {
    "top_relevance_score": 0.83,
    "retrieval_elapsed_sec": 0.12,
    "vector_backend": "milvus",
    "iterative_retrieve": {
      "enabled": true,
      "selected_pass": "primary",
      "passes": [
        { "pass": "primary", "citations": 1, "top_relevance_score": 0.83 },
        { "pass": "fallback", "citations": 0, "top_relevance_score": 0.0 }
      ]
    }
  },
  "has_evidence": true,
  "abstain_triggered": false,
  "abstain_reason": null,
  "retrieval_trace": {
    "schema": "mimirq.retrieval_trace.v1",
    "selected_pass": "primary",
    "passes": [
      {
        "pass": "primary",
        "trace": {
          "schema": "mimirq.retrieval_trace_pass.v1",
          "retrieval_mode": "hybrid",
          "rewrite": { "enabled": false, "used": false },
          "expansions": { "alias": { "enabled": false, "used": false, "count": 0 } }
        }
      }
    ]
  },
  "query_debug": {
    "original": "What is the refund policy for annual plans?",
    "normalized": "refund policy annual plan",
    "applied_rules": ["..."],
    "expansions": [
      { "kind": "kgq", "expanded_text": "refund policy annual plan ACME" }
    ]
  }
}
```

### Response Schema

- `schema`: response schema identifier (currently `mimirq.evidence.v1`). Downstream consumers can use this to
  version their parsing logic without relying on fragile field presence checks.

### Retrieval Trace (Stable)

- `retrieval_trace` is a **stable, versioned trace** intended for downstream provenance parsing.
- It is intentionally separate from:
  - `metrics`: free-form counters (best-effort; may change over time)
  - `query_debug`: best-effort debug payload (may include text; may gain fields)

Schema notes:
- `retrieval_trace.schema` is currently `mimirq.retrieval_trace.v1`.
- Each pass item contains a nested trace with `trace.schema = mimirq.retrieval_trace_pass.v1`.
- This object is designed for **machine parsing** of “what happened” (rewrite/expansions/fusion/post-rerank),
  without depending on ad hoc `metrics` keys.
- Each pass trace may include a `retrieval_config` fingerprint:
  - `retrieval_config.schema = mimirq.retrieval_config.v1`
  - `retrieval_config.hash`: stable, PII-safe config hash (does **not** include raw query text or scope ids)

### Query Debug (Optional)

- `query_debug` is a **best-effort debug payload** for diagnostics and retrieval tuning.
- It may be `null` or omitted in some cases (or gain additional fields over time).
- It is intentionally bounded (to avoid huge payloads) and should **not** be relied on for business logic.
- When KG query expansion is enabled (`KG_ENABLED=true`, `KG_CHAT_ENABLED=true`, `RAG_KG_QUERY_EXPANSION_ENABLED=true`),
  you may see KG-derived query variants in `query_debug.expansions` (e.g. entries with `kind="kgq"`).

### How To Interpret

- `has_evidence=true`:
  - The system found at least one evidence chunk and did **not** trigger the abstain gate.
  - Downstream answer pipelines can proceed (ideally with citations / grounding).
- `has_evidence=false` or `abstain_triggered=true`:
  - Treat as **“not found / insufficient evidence”**.
  - Downstream pipelines should abstain or ask the user to ingest more documents / refine scope.

### Retrieval Roles (Optional)

Each citation may include a `retrieval_role` field that explains where it came from:
- `main`: the primary query
- `alias` / `dict`: deterministic query expansions
- `mq` / `subq` / `hyde`: LLM-assisted expansions (when enabled)
- `kgq`: KG-derived query expansion (entity name appended to query)
- `kg`: KG “chunk injection” (inject KG-linked chunks as extra evidence candidates)

### Score Fields (Best-effort)

Each citation includes several score fields that are useful for debugging and offline training:
- `relevance_score`: final score used for ordering (post-fusion; may be rerank score when reranked)
- `vector_score`, `bm25_score`: channel support signals
- `lexical_score`, `sparse_score`: additional sparse-channel signals (when enabled)
- `retrieval_score`: original pre-rerank score (present when reranking was applied)
- `rerank_score`: reranker score (present when reranking was applied)

## Iterative Evidence Retrieval (Optional)

By default, the endpoint runs **one primary retrieval pass**.

When enabled, the server can run one additional **fallback** retrieval pass if the primary pass returns
no usable evidence (e.g. empty citations, or abstain triggered). This is useful for “evidence discovery”
workloads where recall is more important than latency.

Environment variables:
- `EVIDENCE_ITERATIVE_RETRIEVE_ENABLED=true|false`
- `EVIDENCE_ITERATIVE_RETRIEVE_MAX_PASSES=2` (currently primary + one fallback)
- `EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_PROFILE=coverage80|recall50|recall20`
- `EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_MODE=keyword|hybrid|vector|mmr`

When enabled, the server annotates:
- `metrics.iterative_retrieve.selected_pass`: `"primary"` or `"fallback"`
- `metrics.iterative_retrieve.passes`: summary of each pass (citations, top score, elapsed)

## Retrieval Profiles

Supported presets:
- `recall20`: debug baseline (top_k >= 20, score_threshold = 0.0)
- `recall50`: production default for evidence discovery (top_k >= 50, score_threshold = 0.0)
- `coverage80`: aggressive coverage preset (top_k >= 80, score_threshold = 0.0)

## Compatibility Notes

`citations` is returned as a list of JSON objects and may gain additional fields over time.
Consumers should treat unknown fields as forward-compatible.

## Prometheus Metrics (Optional)

When `PROMETHEUS_ENABLED=true`, the Evidence API emits low-cardinality Prometheus metrics:
- `rag_evidence_retrieve_total`
- `rag_evidence_retrieve_duration_seconds`
- `rag_evidence_retrieve_citations_count`
- `rag_evidence_retrieve_top_score`

Labels intentionally avoid tenant/dataset/query to keep cardinality safe.

## Evidence Post-fusion Rerank (Optional)

For retrieval-only “evidence discovery” workloads, it can be useful to apply a fast, deterministic reranker
after fusion, without changing the retrieval stack itself.

Environment variables:
- `EVIDENCE_POST_RERANK_ENABLED=true|false`
- `EVIDENCE_POST_RERANK_PROVIDER=ltr|colbert|...`
- `EVIDENCE_POST_RERANK_TOP_N=30`
- `EVIDENCE_POST_RERANK_CACHE_ENABLED=true|false`
- `EVIDENCE_POST_RERANK_CACHE_BACKEND=memory|redis`
- `EVIDENCE_POST_RERANK_CACHE_TTL_SEC=30`
- `EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES=1024` (`memory` backend only)

When enabled, the orchestrator will rerank the top-N candidates and annotate:
- `citations[*].reranker_provider`, `citations[*].rerank_score`, `citations[*].retrieval_score` (best-effort)
- `metrics.evidence_post_rerank_*` (used, elapsed, provider, error, etc)

Cache notes:
- `memory` keeps the post-rerank cache process-local and is suitable for single-replica deployments.
- `redis` uses the shared Redis cluster configured by `REDIS_URL`, which keeps cache hits valid across API replicas.
- Cache keys are PII-safe stable hashes; values store only ordered chunk ids plus numeric scores.
