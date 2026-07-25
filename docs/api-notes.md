# API Notes

This document contains **hand-written API usage notes** that complement the generated OpenAPI reference (see [API.md](./API.md) for the doc entry points).

## Evidence API (Retrieval-Only)

Endpoint:

`POST /api/v1/rag/retrieve`

Use this endpoint when you want to answer:

> “Does the corpus contain evidence for this query?”

It performs retrieval only (no answer generation) and returns `citations` plus explicit guardrail signals.

### Example: Dataset-scoped high recall (coverage)

```json
{
  "query": "What is the refund policy for annual plans?",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "document_ids": [],
  "history": [],
  "rag_config": {
    "retrieval_profile": "coverage80"
  }
}
```

### Example: Strict recall gate (debug baseline)

```json
{
  "query": "What is the refund policy for annual plans?",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "document_ids": [],
  "history": [],
  "rag_config": {
    "retrieval_profile": "recall20",
    "top_k": 20,
    "score_threshold": 0.0
  }
}
```

### Response (shape)

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
    "vector_backend": "milvus"
  },
  "has_evidence": true,
  "abstain_triggered": false,
  "abstain_reason": null,
  "retrieval_trace": {
    "schema": "mimirq.retrieval_trace.v1",
    "selected_pass": "primary",
    "passes": [
      { "pass": "primary", "trace": { "schema": "mimirq.retrieval_trace_pass.v1" } }
    ]
  }
}
```

Optional best-effort fields: `evidence_capsule`（immutable replay capsule，见 `docs/guides/evidence_capsule.md`）、`query_debug`（查询归一化/扩展调试信息）。

See also: `docs/guides/evidence_api.md`.
