from typing import Any


def evaluate_retrieval_metrics(
    *,
    gold_chunk_ids: list[str],
    retrieved_chunk_ids: list[str],
    cited_chunk_ids: list[str],
    recall_k: int,
) -> dict[str, Any]:
    gold = [str(item).strip() for item in gold_chunk_ids or [] if str(item or "").strip()]
    retrieved = [str(item).strip() for item in retrieved_chunk_ids or [] if str(item or "").strip()][
        : max(1, int(recall_k or 1))
    ]
    cited = [str(item).strip() for item in cited_chunk_ids or [] if str(item or "").strip()]

    if not gold:
        return {"recall_at_k": 0.0, "citation_coverage": 0.0}

    recall_hits = len(set(gold) & set(retrieved))
    cite_hits = len(set(gold) & set(cited))
    return {
        "recall_at_k": round(recall_hits / len(set(gold)), 4),
        "citation_coverage": round(cite_hits / len(set(gold)), 4),
    }
