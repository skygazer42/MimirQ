# Retrieval Fusion (Multi-Channel)

This project supports multiple retrieval channels (dense + lexical + sparse). A **fusion strategy** merges those channel outputs into a single ranked candidate list.

Why this matters for a retrieval-only “evidence” platform:
- Different channels excel at different query types.
  - Dense (vector): semantic similarity, paraphrases.
  - BM25: keyword-heavy queries.
  - Lexical DB (FTS/pg_trgm): codes, numbers, exact phrases.
  - Sparse (SPLADE-style): term expansion / “semantic lexical”.
- Raw scores are not directly comparable across channels, so fusion must be explicit, deterministic, and observable.

## Channels

The `HybridRetriever` merges up to four channels:
- `vector`: dense embedding search (Milvus/Chroma/etc.)
- `bm25`: in-memory BM25 over scoped corpus
- `lexical_db`: Postgres FTS / pg_trgm fallback
- `sparse`: optional SPLADE-style retrieval

## Fusion Strategies

The fusion strategy is controlled by:
- Global default: `RETRIEVAL_FUSION_STRATEGY` in `app/core/config.py`
- Per-request override (recommended for ablations): `rag_config.fusion_strategy` on Evidence API / LangGraph path

Supported values:

### `linear` (default)

- Min-max normalize each channel to `[0,1]`.
- Compute a fused score:
  - If both dense + keyword channels present: `alpha * vector + (1-alpha) * keyword`
  - Keyword score is `max(bm25, lexical_db, sparse)` per candidate.

Good baseline when channel scores are stable and calibrated.

### `rrf`

Reciprocal Rank Fusion across channels:
- Convert each channel list to ranks (1..N).
- Fused raw score is `sum(1/(k + rank_channel))` across channels.
- Final `score` is min-max normalized for display.

Good when score scales differ across channels.

### `budgeted_rrf`

Budgeted RRF is designed for evidence retrieval where you want **cross-channel coverage** in the *visible* top-k prefix.

Mechanics:
1. Compute RRF fused scores (like `rrf`).
2. Select a **top-k prefix** that enforces per-channel **quotas** (budgets), with **dedup** by `(document_id, chunk_index)` key.
3. Sort the selected prefix by fused score and append the remaining candidates.

Extra observability fields are attached per candidate:
- `vector_rank_score`, `bm25_rank_score`, `lexical_rank_score`, `sparse_rank_score`
  - Each is `1/rank` within that channel (0.0 if the candidate is absent from the channel).

#### Defaults

If no per-request budgets are provided, `budgeted_rrf` uses a small heuristic for the top-k prefix:
- `vector`: ~50% of `top_k`
- remaining “keyword” quota split evenly across `bm25` and `lexical`
- `sparse`: 0 by default (set explicitly if you want it in the prefix)

#### Request Overrides (Evidence API / LangGraph)

In the request `rag_config` you can override:
- `fusion_strategy`: `linear | rrf | budgeted_rrf`
- `fusion_budgets`: per-channel quotas for the visible top-k prefix
- `fusion_min_scores`: per-channel minimum `rank_score` threshold

Example:

```json
{
  "query": "PCI-DSS 4.0 requirement 10.4.2",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "document_ids": [],
  "rag_config": {
    "retrieval_profile": "recall50",
    "retrieval_mode": "hybrid",
    "top_k": 50,
    "score_threshold": 0.0,
    "fusion_strategy": "budgeted_rrf",
    "fusion_budgets": { "vector": 25, "bm25": 10, "lexical": 10, "sparse": 5 },
    "fusion_min_scores": { "lexical": 0.5 }
  }
}
```

Notes:
- Budgets/min-scores are only used when `fusion_strategy=budgeted_rrf` (ignored otherwise).
- `fusion_min_scores` gates low-ranked “tail” candidates from a channel, using `rank_score = 1/rank`.

### `weighted`

Weighted fusion is a deterministic alternative to `linear` when you want explicit weights per channel:

- Min-max normalize each channel to `[0,1]` (same normalization pass used by other fusion paths).
- Compute a fused score per candidate:
  - `score = w_vector * vector + w_bm25 * bm25 + w_lexical * lexical + w_sparse * sparse`
- Weights are normalized to sum=1 (missing keys are treated as 0).
- If weights are missing/invalid, the retriever falls back to `linear` fusion (safe default).

#### Request Overrides (Evidence API / LangGraph)

In the request `rag_config` you can override:
- `fusion_strategy`: `weighted`
- `fusion_weights`: per-channel weights (keys: `vector`, `bm25`, `lexical`, `sparse`)

Example:

```json
{
  "query": "PCI-DSS 4.0 requirement 10.4.2",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "document_ids": [],
  "rag_config": {
    "retrieval_profile": "recall50",
    "retrieval_mode": "hybrid",
    "top_k": 50,
    "fusion_strategy": "weighted",
    "fusion_weights": { "vector": 0.55, "bm25": 0.25, "lexical": 0.15, "sparse": 0.05 }
  }
}
```

#### Per-Dataset Defaults

You can persist per-dataset defaults under `datasets.metadata.rag_defaults` (recommended once weights are validated):

```json
{
  "rag_defaults": {
    "fusion_strategy": "weighted",
    "fusion_weights": { "vector": 0.55, "bm25": 0.25, "lexical": 0.15, "sparse": 0.05 }
  }
}
```

#### Learning Weights (Offline)

For a simple, deterministic weight fit loop:

1) Learn weights via Evidence API (grid search):

```bash
python scripts/learn_fusion_weights_offline.py \\
  --cases runs/regression/cases.json \\
  --base-url http://localhost:8000/api/v1 \\
  --tenant-id <TENANT_UUID> \\
  --user-id <ACCOUNT_ID> \\
  --step 0.2 \\
  --objective mrr \\
  --out-weights runs/fusion_weights/best.json
```

2) Apply to a dataset (safe by default; requires `--execute`):

```bash
python scripts/apply_fusion_weights_to_dataset.py \\
  --dataset-id <DATASET_UUID> \\
  --weights runs/fusion_weights/best.json \\
  --execute
```

Rollback to defaults:

```bash
python scripts/apply_fusion_weights_to_dataset.py --dataset-id <DATASET_UUID> --clear --execute
```

## Offline Evaluation (Report)

Use `scripts/eval_retrieval_fusion_offline.py` to compare fusion variants on a regression cases bundle through the Evidence API.

### Run

```bash
python scripts/eval_retrieval_fusion_offline.py \\
  --cases runs/regression/cases.json \\
  --base-url http://localhost:8000/api/v1 \\
  --tenant-id <TENANT_UUID> \\
  --user-id <ACCOUNT_ID> \\
  --out-json runs/fusion_eval/result.json \\
  --out-md runs/fusion_eval/report.md
```

By default the script compares:
- `base` (no fusion override, uses server defaults)
- `budgeted_rrf` (per-request override)

### Variant Matrix (Optional)

To compare multiple variants in one run, pass a matrix JSON:

```json
{
  "base": {
    "label": "linear",
    "rag_config": { "fusion_strategy": "linear" }
  },
  "variants": [
    { "label": "rrf", "rag_config": { "fusion_strategy": "rrf" } },
    {
      "label": "budgeted_rrf_quotas",
      "rag_config": {
        "fusion_strategy": "budgeted_rrf",
        "fusion_budgets": { "vector": 25, "bm25": 10, "lexical": 10, "sparse": 5 },
        "fusion_min_scores": { "lexical": 0.5 }
      }
    }
  ]
}
```

Then:

```bash
python scripts/eval_retrieval_fusion_offline.py --cases ... --matrix runs/fusion_eval/matrix.json
```
