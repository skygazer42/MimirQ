from __future__ import annotations

from typing import Any


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _coerce_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _dedup_ids(raw_items: Any, *, key: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items or []:
        d = _coerce_dict(item)
        raw = d.get(key)
        if not raw:
            continue
        cid = str(raw)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def build_regression_sample(case: Any, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Build kwargs for RAGAS SingleTurnSample plus per-item meta used for audit/gates.

    This is intentionally pure-ish (no DB access) so it can be unit-tested.
    """
    question = str(item.get("question") or item.get("user_input") or "")
    response = str(item.get("response") or "")
    retrieved_contexts = list(item.get("retrieved_contexts") or [])

    expected_answer = _get(case, "expected_answer", None)
    reference = str(expected_answer or "")

    reference_sources = _get(case, "reference_sources", None) or []
    reference_context_ids = _dedup_ids(reference_sources, key="chunk_id")
    reference_contexts: list[str] = []
    for src in reference_sources or []:
        d = _coerce_dict(src)
        quote = str(d.get("quote") or "").strip()
        if quote:
            reference_contexts.append(quote)

    citations = item.get("citations") or []
    retrieved_context_ids = _dedup_ids(citations, key="chunk_id")

    # Retrieval quality signals (non-LLM):
    # - recall: fraction of human-verified evidence chunks that were retrieved
    # - hit@k: whether any evidence chunk appears in the top-k retrieved list
    ref_set = set(reference_context_ids or [])
    ret_list = list(retrieved_context_ids or [])
    ret_set = set(ret_list)

    retrieval_recall: float | None = None
    retrieval_hit: bool | None = None
    hit_at_1: bool | None = None
    hit_at_3: bool | None = None
    hit_at_5: bool | None = None
    hit_at_10: bool | None = None
    if ref_set:
        hits = len(ref_set & ret_set)
        retrieval_recall = round(hits / max(1, len(ref_set)), 4)
        retrieval_hit = bool(hits > 0)

        def _hit_at(k: int) -> bool:
            return any(cid in ref_set for cid in ret_list[: max(0, int(k or 0))])

        hit_at_1 = _hit_at(1)
        hit_at_3 = _hit_at(3)
        hit_at_5 = _hit_at(5)
        hit_at_10 = _hit_at(10)

    top_rel = item.get("top_relevance_score")
    try:
        top_rel_f = float(top_rel) if top_rel is not None else None
    except Exception:
        top_rel_f = None

    meta = {
        "abstain_triggered": bool(item.get("abstain_triggered")) if "abstain_triggered" in item else None,
        "abstain_reason": item.get("abstain_reason"),
        "top_relevance_score": top_rel_f,
        "retrieval_recall": retrieval_recall,
        "retrieval_hit": retrieval_hit,
        "retrieval_hit_at_1": hit_at_1,
        "retrieval_hit_at_3": hit_at_3,
        "retrieval_hit_at_5": hit_at_5,
        "retrieval_hit_at_10": hit_at_10,
    }

    sample_kwargs = {
        "user_input": question,
        "response": response,
        "retrieved_contexts": retrieved_contexts,
        "reference": reference,
        "reference_context_ids": reference_context_ids,
        "retrieved_context_ids": retrieved_context_ids,
        "reference_contexts": reference_contexts,
    }

    return sample_kwargs, meta


def build_regression_item_meta(*, sample_kwargs: dict[str, Any] | None, item_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Prepare a JSON-safe meta payload for RagasRegressionItem storage."""
    sample = dict(sample_kwargs or {})
    meta = dict(item_meta or {})

    return {
        "reference_context_ids": list(sample.get("reference_context_ids") or []),
        "retrieved_context_ids": list(sample.get("retrieved_context_ids") or []),
        "abstain_triggered": meta.get("abstain_triggered"),
        "abstain_reason": meta.get("abstain_reason"),
        "top_relevance_score": meta.get("top_relevance_score"),
        "retrieval_recall": meta.get("retrieval_recall"),
        "retrieval_hit": meta.get("retrieval_hit"),
        "retrieval_hit_at_1": meta.get("retrieval_hit_at_1"),
        "retrieval_hit_at_3": meta.get("retrieval_hit_at_3"),
        "retrieval_hit_at_5": meta.get("retrieval_hit_at_5"),
        "retrieval_hit_at_10": meta.get("retrieval_hit_at_10"),
    }
