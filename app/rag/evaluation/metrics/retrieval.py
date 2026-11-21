from typing import Any


def _normalize_ids(values: list[str]) -> list[str]:
    return [str(item).strip() for item in values or [] if item.strip()]


def evaluate_retrieval_metrics(
    *,
    gold_chunk_ids: list[str],
    retrieved_chunk_ids: list[str],
    cited_chunk_ids: list[str],
    recall_k: int,
) -> dict[str, Any]:
    gold = _normalize_ids(gold_chunk_ids)
    retrieved = _normalize_ids(retrieved_chunk_ids)[: max(1, int(recall_k or 1))]
    cited = _normalize_ids(cited_chunk_ids)

    if not gold:
        return {"recall_at_k": 0.0, "citation_coverage": 0.0}

    gold_ids = set(gold)
    recall_hits = len(gold_ids & set(retrieved))
    cite_hits = len(gold_ids & set(cited))
    return {
        "recall_at_k": round(recall_hits / len(gold_ids), 4),
        "citation_coverage": round(cite_hits / len(gold_ids), 4),
    }
