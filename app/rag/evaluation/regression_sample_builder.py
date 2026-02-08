from __future__ import annotations

import math
import re
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


_WS_RE = re.compile(r"\s+")


def _collapse_ws(text: Any) -> str:
    return _WS_RE.sub(" ", str(text or "").strip())


def _stable_ref_key(src: Any) -> str | None:
    d = _coerce_dict(src)
    dk = str(d.get("doc_pipeline_key") or "").strip()
    if not dk:
        return None
    idx_raw = d.get("chunk_index")
    try:
        idx = int(idx_raw) if idx_raw is not None else None
    except Exception:
        idx = None
    if idx is None or idx < 0:
        return None
    return f"{dk}:{idx}"


def _stable_citation_key(cit: Any) -> str | None:
    d = _coerce_dict(cit)
    dk = str(d.get("doc_pipeline_key") or "").strip()
    if not dk:
        return None
    idx_raw = d.get("chunk_index")
    try:
        idx = int(idx_raw) if idx_raw is not None else None
    except Exception:
        idx = None
    if idx is None or idx < 0:
        return None
    return f"{dk}:{idx}"


def _quote_signature(text: Any, *, max_chars: int = 120) -> str | None:
    """
    Produce a small, normalized quote signature used for best-effort matching
    when chunk ids change.
    """
    max_chars = max(20, int(max_chars or 0))
    norm = _collapse_ws(text).casefold()
    if len(norm) < 24:
        return None
    return norm[:max_chars]


def _citation_text_for_quote_match(cit: Any) -> str:
    d = _coerce_dict(cit)
    # Prefer citation snippet, fall back to retrieved_contexts later if needed.
    return _collapse_ws(d.get("chunk_content") or d.get("quote") or "").casefold()


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

    citations_ranked: list[Any] = []
    seen_cids: set[str] = set()
    for c in citations or []:
        d = _coerce_dict(c)
        cid = str(d.get("chunk_id") or "").strip()
        if not cid:
            continue
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        citations_ranked.append(c)

    # Retrieval quality signals (non-LLM):
    # - recall: fraction of human-verified evidence sources that were matched by retrieval
    # - hit@k: whether any evidence source appears in the top-k retrieved list
    # Matching strategy (best-effort):
    # 1) chunk_id exact match (fast path)
    # 2) doc_pipeline_key + chunk_index match (version-stable)
    # 3) quote signature substring match (fallback when ids drift)
    ref_set = set(reference_context_ids or [])
    ret_list = list(retrieved_context_ids or [])
    ret_set = set(ret_list)

    ref_keys: list[str] = []
    ref_quotes: list[str] = []
    for src in reference_sources or []:
        k = _stable_ref_key(src)
        if k:
            ref_keys.append(k)
        qsig = _quote_signature(_coerce_dict(src).get("quote"))
        if qsig:
            ref_quotes.append(qsig)
    ref_key_set = set(ref_keys)

    cit_keys: list[str] = []
    cit_texts: list[str] = []
    for c in citations_ranked:
        ck = _stable_citation_key(c)
        if ck:
            cit_keys.append(ck)
        cit_texts.append(_citation_text_for_quote_match(c))
    cit_key_set = set(cit_keys)
    cit_text_joined = "\n".join([t for t in cit_texts if t]) if cit_texts else ""

    def _citation_matches_any_ref(i: int) -> bool:
        if i < 0 or i >= len(citations_ranked):
            return False
        d = _coerce_dict(citations_ranked[i])
        cid = str(d.get("chunk_id") or "").strip()
        if cid and cid in ref_set:
            return True

        ck = _stable_citation_key(d)
        if ck and ck in ref_key_set:
            return True

        if ref_quotes:
            text_i = _citation_text_for_quote_match(d)
            if text_i:
                for qsig in ref_quotes:
                    if qsig and qsig in text_i:
                        return True
        return False

    def _ref_source_matched(src: Any) -> bool:
        d = _coerce_dict(src)
        cid = str(d.get("chunk_id") or "").strip()
        if cid and cid in ret_set:
            return True
        k = _stable_ref_key(src)
        if k and k in cit_key_set:
            return True
        qsig = _quote_signature(d.get("quote"))
        if qsig and cit_text_joined and qsig in cit_text_joined:
            return True
        return False

    retrieval_recall: float | None = None
    retrieval_hit: bool | None = None
    retrieval_mrr: float | None = None
    retrieval_ndcg_at_10: float | None = None
    retrieval_ndcg_at_20: float | None = None
    hit_at_1: bool | None = None
    hit_at_3: bool | None = None
    hit_at_5: bool | None = None
    hit_at_10: bool | None = None
    hit_at_20: bool | None = None
    if reference_sources:
        ref_total = len(list(reference_sources or []))
        matched_refs = sum(1 for src in (reference_sources or []) if _ref_source_matched(src))
        retrieval_recall = round(float(matched_refs) / max(1, int(ref_total)), 4)
        retrieval_hit = bool(matched_refs > 0)

        # Rank-based metrics consider a citation "relevant" if it matches any reference source.
        rank_first: int | None = None
        relevance_flags: list[bool] = []
        for i in range(len(citations_ranked)):
            rel = _citation_matches_any_ref(i)
            relevance_flags.append(rel)
            if rel and rank_first is None:
                rank_first = i + 1

        if rank_first is not None and rank_first > 0:
            retrieval_mrr = round(1.0 / float(rank_first), 4)
        else:
            retrieval_mrr = 0.0

        # NDCG@K: binary relevance. Ideal ordering assumes each reference source can be hit by one retrieved item.
        def _ndcg_at(k: int) -> float:
            kk = max(1, int(k or 0))
            dcg = 0.0
            for idx, rel in enumerate(relevance_flags[:kk], 1):
                if rel:
                    dcg += 1.0 / math.log2(idx + 1)

            idcg = 0.0
            for idx in range(1, min(kk, ref_total) + 1):
                idcg += 1.0 / math.log2(idx + 1)
            return round(dcg / idcg, 4) if idcg > 0.0 else 0.0

        retrieval_ndcg_at_10 = _ndcg_at(10)
        retrieval_ndcg_at_20 = _ndcg_at(20)

        def _hit_at(k: int) -> bool:
            kk = max(0, int(k or 0))
            return any(relevance_flags[:kk]) if kk > 0 else False

        hit_at_1 = _hit_at(1)
        hit_at_3 = _hit_at(3)
        hit_at_5 = _hit_at(5)
        hit_at_10 = _hit_at(10)
        hit_at_20 = _hit_at(20)

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
        "retrieval_mrr": retrieval_mrr,
        "retrieval_ndcg_at_10": retrieval_ndcg_at_10,
        "retrieval_ndcg_at_20": retrieval_ndcg_at_20,
        "retrieval_hit_at_1": hit_at_1,
        "retrieval_hit_at_3": hit_at_3,
        "retrieval_hit_at_5": hit_at_5,
        "retrieval_hit_at_10": hit_at_10,
        "retrieval_hit_at_20": hit_at_20,
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
        "retrieval_mrr": meta.get("retrieval_mrr"),
        "retrieval_ndcg_at_10": meta.get("retrieval_ndcg_at_10"),
        "retrieval_ndcg_at_20": meta.get("retrieval_ndcg_at_20"),
        "retrieval_hit_at_1": meta.get("retrieval_hit_at_1"),
        "retrieval_hit_at_3": meta.get("retrieval_hit_at_3"),
        "retrieval_hit_at_5": meta.get("retrieval_hit_at_5"),
        "retrieval_hit_at_10": meta.get("retrieval_hit_at_10"),
        "retrieval_hit_at_20": meta.get("retrieval_hit_at_20"),
    }
