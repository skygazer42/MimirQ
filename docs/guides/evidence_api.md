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
  "abstain_reason": null
}
```

### How To Interpret

- `has_evidence=true`:
  - The system found at least one evidence chunk and did **not** trigger the abstain gate.
  - Downstream answer pipelines can proceed (ideally with citations / grounding).
- `has_evidence=false` or `abstain_triggered=true`:
  - Treat as **“not found / insufficient evidence”**.
  - Downstream pipelines should abstain or ask the user to ingest more documents / refine scope.

## Retrieval Profiles

Supported presets:
- `recall20`: debug baseline (top_k >= 20, score_threshold = 0.0)
- `recall50`: production default for evidence discovery (top_k >= 50, score_threshold = 0.0)
- `coverage80`: aggressive coverage preset (top_k >= 80, score_threshold = 0.0)

## Compatibility Notes

`citations` is returned as a list of JSON objects and may gain additional fields over time.
Consumers should treat unknown fields as forward-compatible.

