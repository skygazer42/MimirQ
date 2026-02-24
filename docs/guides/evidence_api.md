# Evidence API (Retrieval-Only)

This guide documents the **retrieval-only** endpoint intended for “evidence discovery”:

- No LLM answer generation
- Returns **evidence chunks** (`citations`) plus guardrail signals
- Designed for downstream systems that want to answer: **“Do we have evidence for this question in the corpus?”**

## Endpoint

`POST /api/v1/rag/retrieve`

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
