"""
Pure helper functions for KG search diagnostics.

These helpers are intentionally dependency-light so they can be unit-tested without
requiring a full backend runtime (DB, Milvus, LLM config, etc.).
"""


import math
from typing import Any


def compute_kg_hit_metrics(*, events: list[dict[str, Any]], evidence_chunk_ids: set[str], k: int) -> dict[str, Any]:
    """
    Compute deterministic retrieval metrics against evidence chunks.

    Definitions (all @K):
    - hit_at_k: any evidence chunk appears in the top-k event list
    - mrr: reciprocal rank of the first evidence hit within top-k (0 if no hit)
    - recall: fraction of evidence chunks covered by the top-k events

    Notes:
    - Evidence is chunk-level, aligned with regression `reference_sources.chunk_id`.
    - KG search events include `chunk_id` so this stays cheap and deterministic.
    """
    kk = max(1, int(k or 0))

    ev_set = {str(x).strip() for x in (evidence_chunk_ids or set()) if str(x).strip()}
    total = int(len(ev_set))
    if total <= 0:
        return {
            "hit_at_k": False,
            "mrr": 0.0,
            "recall": 0.0,
            "ndcg": 0.0,
            "map": 0.0,
            "matched_evidence_chunks": 0,
            "total_evidence_chunks": 0,
            "k": kk,
        }

    matched: set[str] = set()
    first_rank: int | None = None
    dcg = 0.0
    average_precision_acc = 0.0

    for idx, ev in enumerate((events or [])[:kk], 1):
        if not isinstance(ev, dict):
            continue
        cid = str(ev.get("chunk_id") or "").strip()
        if not cid:
            continue
        if cid not in ev_set:
            continue

        matched.add(cid)
        if first_rank is None:
            first_rank = int(idx)
        dcg += 1.0 / math.log2(float(idx) + 1.0)
        average_precision_acc += float(len(matched)) / float(idx)

    hit = bool(matched)
    mrr = 1.0 / float(first_rank) if first_rank is not None and first_rank > 0 else 0.0
    recall = float(len(matched)) / float(total) if total > 0 else 0.0
    ideal_hits = min(total, kk)
    ideal_dcg = sum(1.0 / math.log2(float(rank) + 1.0) for rank in range(1, ideal_hits + 1))
    ndcg = float(dcg / ideal_dcg) if ideal_dcg > 0 else 0.0
    mean_average_precision = float(average_precision_acc / float(total)) if total > 0 else 0.0

    # Keep stable precision in JSON responses.
    return {
        "hit_at_k": hit,
        "mrr": round(float(mrr), 4),
        "recall": round(float(recall), 4),
        "ndcg": round(float(ndcg), 4),
        "map": round(float(mean_average_precision), 4),
        "matched_evidence_chunks": int(len(matched)),
        "total_evidence_chunks": int(total),
        "k": kk,
    }


__all__ = ["compute_kg_hit_metrics"]
