"""Run evidence reranking, cache lookups, and score calibration in one owner."""

import logging
import time
from typing import Any, NotRequired, TypedDict

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.model_policy import PostRerankStageConfig, reject_retired_provider
from app.rag.retrieval.cache.reranking import (
    build_evidence_post_rerank_cache_key,
    fingerprint_rerank_candidates,
    get_cached_evidence_post_rerank_result,
    get_evidence_post_rerank_cache_backend,
    set_cached_evidence_post_rerank_result,
)
from app.rag.retrieval.reranking.factory import get_reranker_for_retrieval
from app.rag.retrieval.reranking.types import RerankCandidate, RerankResult
from app.rag.retrieval.results import _log_orchestrator_fallback, document_key
from app.services.retrieval.corpus_tokens import resolve_corpus_cache_token

logger = logging.getLogger("app.rag.retrieval.orchestrator")
_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE = "Ignoring non-critical retrieval orchestrator fallback failure: %s"


class _PostRerankRow(TypedDict):
    idx: int
    rid: str
    doc: Document
    meta: dict[str, Any]
    retrieval_score: float
    rerank_score: float | None
    retrieval_score_norm: NotRequired[float]
    rerank_score_norm: NotRequired[float | None]
    calibrated_score: NotRequired[float]


def _post_rerank_minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    rng = hi - lo
    if rng <= 0.0:
        return [0.0 for _ in values]
    return [(value - lo) / rng for value in values]


def _retrieval_score(meta: dict[str, Any]) -> float:
    score = meta.get("retrieval_score")
    if score is None:
        score = meta.get("score", 0.0)
    try:
        return float(score or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _post_rerank_row(idx: int, doc: Document) -> _PostRerankRow:
    meta = dict(doc.metadata or {})
    rid = document_key(doc)
    retrieval_score = _retrieval_score(meta)
    rerank_raw = meta.get("rerank_score")
    try:
        rerank_score = float(rerank_raw) if rerank_raw is not None else None
    except (TypeError, ValueError):
        rerank_score = None

    return {
        "idx": idx,
        "rid": rid,
        "doc": doc,
        "meta": meta,
        "retrieval_score": retrieval_score,
        "rerank_score": rerank_score,
    }


def _calibrated_post_rerank_rows(
    rows: list[_PostRerankRow],
    *,
    alpha: float,
) -> list[_PostRerankRow]:
    ranked_rows = [row for row in rows if row["rerank_score"] is not None]
    retrieval_norm = _post_rerank_minmax([row["retrieval_score"] or 0.0 for row in rows])
    rerank_norm_values = _post_rerank_minmax([row["rerank_score"] or 0.0 for row in ranked_rows])
    rerank_norm_by_id = {row["rid"]: rerank_norm_values[index] for index, row in enumerate(ranked_rows)}

    for index, row in enumerate(rows):
        base_norm = retrieval_norm[index]
        rerank_norm = rerank_norm_by_id.get(row["rid"])
        calibrated = base_norm
        if rerank_norm is not None:
            calibrated = (alpha * rerank_norm) + ((1.0 - alpha) * base_norm)
        row["retrieval_score_norm"] = base_norm
        row["rerank_score_norm"] = rerank_norm
        row["calibrated_score"] = calibrated

    return sorted(
        rows,
        key=lambda row: (
            -(row["calibrated_score"] or 0.0),
            -(row["rerank_score_norm"] or -1.0),
            -(row["retrieval_score_norm"] or 0.0),
            row["idx"] or 0,
        ),
    )


def _calibrate_post_rerank_prefix(
    prefix_docs: list[Document],
    *,
    enabled: bool,
    alpha: float,
    stats: dict[str, Any],
) -> tuple[list[Document], bool]:
    if not enabled:
        return prefix_docs, False
    if not prefix_docs:
        stats["skip_reason"] = "no_candidates"
        return prefix_docs, False

    rows = [_post_rerank_row(index, doc) for index, doc in enumerate(prefix_docs)]
    ranked_rows = [row for row in rows if row["rerank_score"] is not None]
    if len(ranked_rows) < 2:
        stats["skip_reason"] = "insufficient_rerank_scores"
        stats["eligible_docs"] = len(ranked_rows)
        return prefix_docs, False

    rows_sorted = _calibrated_post_rerank_rows(rows, alpha=alpha)
    moved = sum(1 for index, row in enumerate(rows_sorted) if row["idx"] != index)
    top_changed = rows_sorted[0]["idx"] != 0

    out_docs: list[Document] = []
    for row in rows_sorted:
        meta = dict(row["meta"])
        calibrated = row["calibrated_score"] or 0.0
        meta["rerank_score_calibrated"] = round(calibrated, 6)
        meta["score"] = calibrated
        doc = row["doc"]
        out_docs.append(
            Document(
                page_content=doc.page_content,
                metadata=meta,
                id=doc.id or meta.get("chunk_id"),
            )
        )

    stats.update(
        {
            "used": True,
            "applied_docs": len(rows),
            "eligible_docs": len(ranked_rows),
            "moved_positions": moved,
            "top_changed": top_changed,
        }
    )
    return out_docs, True


def _resolve_post_rerank_corpus_cache_token(state: dict[str, Any]) -> str | None:
    db = state.get("db")
    tenant_id = state.get("tenant_id")
    if db is None or tenant_id is None:
        return None
    return resolve_corpus_cache_token(
        db,
        tenant_id=tenant_id,
        dataset_id=state.get("dataset_id"),
        document_ids=state.get("document_ids"),
    )


def _build_post_rerank_candidates(
    docs: list[Document],
    *,
    limit: int,
) -> tuple[list[RerankCandidate], dict[str, Document]]:
    candidates: list[RerankCandidate] = []
    id_to_doc: dict[str, Document] = {}
    for doc in docs[:limit]:
        rid = document_key(doc)
        text = (doc.page_content).strip()
        if not text:
            continue
        meta = dict(doc.metadata or {})
        candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
        id_to_doc[rid] = doc
    return candidates, id_to_doc


def _get_cached_post_rerank_result(
    *,
    state: dict[str, Any],
    provider: str,
    top_n: int,
    query_for_retrieval: str,
    candidates: list[RerankCandidate],
    cache_enabled: bool,
    corpus_cache_token: str | None,
) -> tuple[RerankResult | None, str | None, bool, int, int]:
    if not cache_enabled:
        return None, None, False, 0, 0
    if corpus_cache_token is None:
        logger.debug("Skipping evidence post-rerank cache: corpus version token unavailable")
        return None, None, False, 0, 0
    try:
        cand_fp = fingerprint_rerank_candidates(candidates)
        cache_key = build_evidence_post_rerank_cache_key(
            tenant_id=state.get("tenant_id"),
            account_id=state.get("account_id"),
            provider=provider,
            top_n=top_n,
            query=query_for_retrieval,
            candidates_fingerprint=cand_fp,
            corpus_cache_token=corpus_cache_token,
        )
        cached = get_cached_evidence_post_rerank_result(cache_key)
        if cached is not None:
            return cached, cache_key, True, 1, 0
        return None, cache_key, False, 0, 1
    except Exception as exc:
        _log_orchestrator_fallback("_get_cached_post_rerank_result", exc)
        return None, None, False, 0, 0


def _execute_post_rerank(
    *,
    state: dict[str, Any],
    provider: str,
    top_n: int,
    query_for_retrieval: str,
    candidates: list[RerankCandidate],
    cache_enabled: bool,
    cache_key: str | None,
    cached_result: RerankResult | None,
) -> tuple[RerankResult, float]:
    if cached_result is not None:
        return cached_result, 0.0
    reranker = get_reranker_for_retrieval(provider)
    rerank_start = time.time()
    rerank_result = reranker.rerank(
        query=query_for_retrieval,
        candidates=candidates,
        top_n=top_n,
        tenant_id=state.get("tenant_id"),
        query_type=state.get("query_type"),
    )
    if cache_enabled and cache_key:
        try:
            set_cached_evidence_post_rerank_result(cache_key, rerank_result)
        except Exception as exc:
            logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)
    elapsed_sec = rerank_result.elapsed_sec
    if elapsed_sec is None:
        elapsed_sec = time.time() - rerank_start
    return rerank_result, float(elapsed_sec)


def _build_reranked_document(
    *,
    doc: Document,
    meta: dict[str, Any],
) -> Document:
    return Document(
        page_content=doc.page_content,
        metadata=meta,
        id=doc.id or meta.get("chunk_id"),
    )


def _build_reranked_prefix(
    *,
    docs_prefix: list[Document],
    id_to_doc: dict[str, Document],
    rerank_result: RerankResult,
    provider: str,
    elapsed_sec: float,
    model_used: str | None,
    annotate_scores: bool,
) -> list[Document]:
    ordered_prefix: list[Document] = []
    used: set[str] = set()
    rerank_elapsed = round(float(elapsed_sec), 3)

    for rid in rerank_result.ordered_ids:
        doc = id_to_doc.get(rid)
        if doc is None or rid in used:
            continue
        used.add(rid)
        meta = dict(doc.metadata or {})
        if annotate_scores:
            meta["retrieval_score"] = _retrieval_score(meta)
            if rid in rerank_result.score_map:
                meta["rerank_score"] = float(rerank_result.score_map[rid])
                meta["score"] = float(rerank_result.score_map[rid])
            meta["reranker_provider"] = provider
            meta["rerank_elapsed_sec"] = rerank_elapsed
            meta["rerank_model_used"] = model_used
        ordered_prefix.append(_build_reranked_document(doc=doc, meta=meta))

    for doc in docs_prefix:
        rid = document_key(doc)
        if rid in used:
            continue
        meta = dict(doc.metadata or {})
        if annotate_scores:
            meta["retrieval_score"] = _retrieval_score(meta)
            meta.setdefault("reranker_provider", provider)
            meta.setdefault("rerank_elapsed_sec", rerank_elapsed)
            meta.setdefault("rerank_model_used", model_used)
        ordered_prefix.append(_build_reranked_document(doc=doc, meta=meta))
    return ordered_prefix


def _post_rerank_settings(
    state: dict[str, Any],
) -> dict[str, Any]:
    provider = str(settings.EVIDENCE_POST_RERANK_PROVIDER).strip().lower()
    reject_retired_provider(provider, capability="reranker")
    cache_enabled = bool(settings.EVIDENCE_POST_RERANK_CACHE_ENABLED)
    calibration_alpha = settings.EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA
    calibration_alpha = min(1.0, max(0.0, calibration_alpha))
    return {
        "enabled": bool(settings.EVIDENCE_POST_RERANK_ENABLED),
        "pipeline_enabled": bool(settings.EVIDENCE_POST_RERANK_PIPELINE_ENABLED),
        "pipeline": settings.EVIDENCE_POST_RERANK_PIPELINE,
        "provider": provider,
        "top_n": int(settings.EVIDENCE_POST_RERANK_TOP_N),
        "cache_enabled": cache_enabled,
        "cache_backend": get_evidence_post_rerank_cache_backend(),
        "corpus_cache_token": None,
        "score_calibration_enabled": bool(settings.EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED),
        "score_calibration_alpha": calibration_alpha,
    }


def _run_post_rerank_single_mode(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_k: int,
    provider: str,
    top_n: int,
    cache_enabled: bool,
    corpus_cache_token: str | None,
    score_calibration_enabled: bool,
    score_calibration_alpha: float,
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    governed_n = min(int(top_n), len(docs))
    governed_n = max(governed_n, int(top_k))
    governed_n = min(governed_n, len(docs))
    candidates, id_to_doc = _build_post_rerank_candidates(docs, limit=governed_n)
    result: dict[str, Any] = {
        "docs": list(docs),
        "post_rerank_used": False,
        "post_rerank_provider": provider,
        "post_rerank_model_used": None,
        "post_rerank_candidates_n": governed_n,
        "post_rerank_elapsed": 0.0,
        "post_rerank_cache_hits": 0,
        "post_rerank_cache_misses": 0,
        "post_rerank_score_calibration_used": False,
        "post_rerank_skip_reason": "no_candidates",
    }
    if not candidates:
        return result

    cached, cache_key, _, cache_hits, cache_misses = _get_cached_post_rerank_result(
        state=state,
        provider=provider,
        top_n=governed_n,
        query_for_retrieval=query_for_retrieval,
        candidates=candidates,
        cache_enabled=cache_enabled,
        corpus_cache_token=corpus_cache_token,
    )
    rerank_result, elapsed_sec = _execute_post_rerank(
        state=state,
        provider=provider,
        top_n=governed_n,
        query_for_retrieval=query_for_retrieval,
        candidates=candidates,
        cache_enabled=cache_enabled,
        cache_key=cache_key,
        cached_result=cached,
    )
    model_used = rerank_result.model_used
    reranker_provider = rerank_result.provider or provider
    ordered = _build_reranked_prefix(
        docs_prefix=list((docs)[:governed_n]),
        id_to_doc=id_to_doc,
        rerank_result=rerank_result,
        provider=reranker_provider,
        elapsed_sec=elapsed_sec,
        model_used=model_used,
        annotate_scores=True,
    )
    ordered, score_calibration_used = _calibrate_post_rerank_prefix(
        ordered,
        enabled=bool(score_calibration_enabled),
        alpha=float(score_calibration_alpha),
        stats=score_calibration_stats,
    )
    return {
        "docs": ordered + list((docs)[governed_n:]),
        "post_rerank_used": True,
        "post_rerank_provider": reranker_provider,
        "post_rerank_model_used": model_used,
        "post_rerank_candidates_n": governed_n,
        "post_rerank_elapsed": float(elapsed_sec),
        "post_rerank_cache_hits": int(cache_hits),
        "post_rerank_cache_misses": int(cache_misses),
        "post_rerank_score_calibration_used": bool(score_calibration_used),
        "post_rerank_skip_reason": None,
    }


def _stage_top_n(
    *,
    stage: PostRerankStageConfig,
    previous_n: int | None,
    top_n: int,
    docs_count: int,
) -> int:
    stage_n = stage.top_n
    if stage_n == 0:
        stage_n = previous_n if previous_n is not None else top_n
    if previous_n is not None:
        stage_n = min(stage_n, previous_n)
    return min(stage_n, docs_count)


def _pipeline_noop_result(
    *,
    docs: list[Document],
    stages: list[dict[str, Any]],
    cache_hits: int,
    cache_misses: int,
) -> dict[str, Any]:
    return {
        "docs": list(docs),
        "post_rerank_pipeline_stages": stages,
        "post_rerank_pipeline_used": True,
        "post_rerank_used": False,
        "post_rerank_provider": None,
        "post_rerank_model_used": None,
        "post_rerank_candidates_n": 0,
        "post_rerank_elapsed": 0.0,
        "post_rerank_cache_hits": int(cache_hits),
        "post_rerank_cache_misses": int(cache_misses),
        "post_rerank_score_calibration_used": False,
        "post_rerank_skip_reason": "pipeline_noop",
    }


def _append_stage_meta(
    *,
    stages: list[dict[str, Any]],
    provider: str,
    stage_n: int,
    candidates_count: int,
    elapsed_sec: float,
    model_used: str | None,
    cache_hit: bool,
) -> None:
    stages.append(
        {
            "provider": provider,
            "top_n": stage_n,
            "candidates": candidates_count,
            "elapsed_sec": round(float(elapsed_sec), 3),
            "model_used": model_used,
            "cache_hit": bool(cache_hit),
        }
    )


def _run_post_rerank_pipeline_mode(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_n: int,
    pipeline: list[PostRerankStageConfig],
    cache_enabled: bool,
    corpus_cache_token: str | None,
    score_calibration_enabled: bool,
    score_calibration_alpha: float,
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    docs_work: list[Document] = list(docs)
    total_elapsed = 0.0
    previous_n: int | None = None
    final_provider: str | None = None
    final_model_used: str | None = None
    final_n = 0
    stages: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0

    for index, stage in enumerate(pipeline):
        stage_provider = stage.provider

        stage_n = _stage_top_n(
            stage=stage,
            previous_n=previous_n,
            top_n=top_n,
            docs_count=len(docs_work),
        )
        if stage_n <= 0:
            continue

        candidates, id_to_doc = _build_post_rerank_candidates(docs_work, limit=stage_n)
        if not candidates:
            continue

        cached, cache_key, cache_hit, hit_delta, miss_delta = _get_cached_post_rerank_result(
            state=state,
            provider=stage_provider,
            top_n=stage_n,
            query_for_retrieval=query_for_retrieval,
            candidates=candidates,
            cache_enabled=cache_enabled,
            corpus_cache_token=corpus_cache_token,
        )
        cache_hits += int(hit_delta)
        cache_misses += int(miss_delta)
        rerank_result, elapsed_i = _execute_post_rerank(
            state=state,
            provider=stage_provider,
            top_n=stage_n,
            query_for_retrieval=query_for_retrieval,
            candidates=candidates,
            cache_enabled=cache_enabled,
            cache_key=cache_key,
            cached_result=cached,
        )
        total_elapsed += float(elapsed_i)

        used_provider = (rerank_result.provider or stage_provider).strip().lower() or stage_provider
        is_final = index == (len(pipeline) - 1)
        if is_final:
            final_provider = used_provider
            final_model_used = rerank_result.model_used
            final_n = stage_n

        ordered_prefix = _build_reranked_prefix(
            docs_prefix=list(docs_work[:stage_n]),
            id_to_doc=id_to_doc,
            rerank_result=rerank_result,
            provider=used_provider,
            elapsed_sec=total_elapsed,
            model_used=rerank_result.model_used,
            annotate_scores=is_final,
        )
        if is_final:
            ordered_prefix, score_calibration_used = _calibrate_post_rerank_prefix(
                ordered_prefix,
                enabled=bool(score_calibration_enabled),
                alpha=float(score_calibration_alpha),
                stats=score_calibration_stats,
            )
        else:
            score_calibration_used = False
        docs_work = ordered_prefix + list(docs_work[stage_n:])
        previous_n = stage_n
        _append_stage_meta(
            stages=stages,
            provider=used_provider,
            stage_n=stage_n,
            candidates_count=len(candidates),
            elapsed_sec=elapsed_i,
            model_used=rerank_result.model_used,
            cache_hit=cache_hit,
        )
        if score_calibration_used:
            score_calibration_stats["used"] = True

    if final_provider is None or final_n <= 0:
        return _pipeline_noop_result(
            docs=docs,
            stages=stages,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )

    return {
        "docs": docs_work,
        "post_rerank_pipeline_stages": stages,
        "post_rerank_pipeline_used": True,
        "post_rerank_used": True,
        "post_rerank_provider": final_provider,
        "post_rerank_model_used": final_model_used,
        "post_rerank_candidates_n": final_n,
        "post_rerank_elapsed": total_elapsed,
        "post_rerank_cache_hits": cache_hits,
        "post_rerank_cache_misses": cache_misses,
        "post_rerank_score_calibration_used": bool(score_calibration_stats["used"]),
        "post_rerank_skip_reason": None,
    }


def _initial_post_rerank_result(
    *,
    docs: list[Document],
    settings_meta: dict[str, Any],
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "docs": list(docs),
        "post_rerank_enabled": bool(settings_meta["enabled"]),
        "post_rerank_used": False,
        "post_rerank_provider": settings_meta["provider"],
        "post_rerank_model_used": None,
        "post_rerank_elapsed": 0.0,
        "post_rerank_error": None,
        "post_rerank_candidates_n": 0,
        "post_rerank_skip_reason": None,
        "post_rerank_cache_enabled": bool(settings_meta["cache_enabled"]),
        "post_rerank_cache_backend": settings_meta["cache_backend"],
        "post_rerank_cache_hits": 0,
        "post_rerank_cache_misses": 0,
        "post_rerank_pipeline_enabled": bool(settings_meta["pipeline_enabled"]),
        "post_rerank_pipeline_used": False,
        "post_rerank_pipeline": [],
        "post_rerank_pipeline_stages": [],
        "post_rerank_score_calibration_used": False,
        "post_rerank_score_calibration_stats": score_calibration_stats,
    }


def _apply_pipeline_result(
    *,
    result: dict[str, Any],
    pipeline_result: dict[str, Any],
) -> bool:
    result.update(pipeline_result)
    result["post_rerank_pipeline_used"] = True
    result["post_rerank_score_calibration_used"] = bool(pipeline_result["post_rerank_score_calibration_used"])
    if not bool(pipeline_result["post_rerank_used"]) and result["post_rerank_skip_reason"] is None:
        result["post_rerank_skip_reason"] = "pipeline_noop"
    return bool(pipeline_result["post_rerank_used"])


def _apply_single_result(
    *,
    result: dict[str, Any],
    single_result: dict[str, Any],
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    result["docs"] = list(single_result["docs"])
    result["post_rerank_used"] = bool(single_result["post_rerank_used"])
    result["post_rerank_provider"] = single_result["post_rerank_provider"]
    result["post_rerank_model_used"] = single_result["post_rerank_model_used"]
    result["post_rerank_candidates_n"] = int(single_result["post_rerank_candidates_n"])
    result["post_rerank_elapsed"] = float(single_result["post_rerank_elapsed"])
    result["post_rerank_cache_hits"] = int(result["post_rerank_cache_hits"]) + int(
        single_result["post_rerank_cache_hits"]
    )
    result["post_rerank_cache_misses"] = int(result["post_rerank_cache_misses"]) + int(
        single_result["post_rerank_cache_misses"]
    )
    single_skip_reason = single_result["post_rerank_skip_reason"]
    if single_skip_reason is not None:
        result["post_rerank_skip_reason"] = single_skip_reason
    score_calibration_stats["used"] = single_result["post_rerank_score_calibration_used"]
    result["post_rerank_score_calibration_used"] = bool(score_calibration_stats["used"])
    result["post_rerank_score_calibration_stats"] = score_calibration_stats
    return result


def _run_post_rerank_stage(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_k: int,
) -> dict[str, Any]:
    settings_meta = _post_rerank_settings(state)
    score_calibration_stats: dict[str, Any] = {
        "enabled": bool(settings_meta["score_calibration_enabled"]),
        "alpha": round(float(settings_meta["score_calibration_alpha"]), 4),
        "used": False,
    }
    result = _initial_post_rerank_result(
        docs=docs,
        settings_meta=settings_meta,
        score_calibration_stats=score_calibration_stats,
    )
    if not settings_meta["enabled"]:
        return result
    if not docs:
        result["post_rerank_skip_reason"] = "no_candidates"
        return result

    provider = settings_meta["provider"]

    top_n = settings_meta["top_n"]
    if top_n <= 0:
        top_n = len(docs)
    top_n = min(int(top_n), len(docs))

    try:
        pipeline: list[PostRerankStageConfig] = []
        if settings_meta["pipeline_enabled"]:
            pipeline = settings_meta["pipeline"]
            result["post_rerank_pipeline"] = [stage.model_dump() for stage in pipeline]
        if settings_meta["cache_enabled"] and (
            provider not in {"none", "off", "false", "0"}
            or any(stage.provider not in {"none", "off", "false", "0"} for stage in pipeline)
        ):
            settings_meta["corpus_cache_token"] = _resolve_post_rerank_corpus_cache_token(state)
        if pipeline:
            pipeline_result = _run_post_rerank_pipeline_mode(
                state=state,
                docs=list(docs),
                query_for_retrieval=query_for_retrieval,
                top_n=int(top_n),
                pipeline=pipeline,
                cache_enabled=bool(settings_meta["cache_enabled"]),
                corpus_cache_token=settings_meta["corpus_cache_token"],
                score_calibration_enabled=bool(settings_meta["score_calibration_enabled"]),
                score_calibration_alpha=float(settings_meta["score_calibration_alpha"]),
                score_calibration_stats=score_calibration_stats,
            )
            if _apply_pipeline_result(result=result, pipeline_result=pipeline_result):
                return result

        if provider in {"none", "off", "false", "0"}:
            result["post_rerank_skip_reason"] = "provider_off"
            return result

        single_result = _run_post_rerank_single_mode(
            state=state,
            docs=list(result["docs"]),
            query_for_retrieval=query_for_retrieval,
            top_k=int(top_k),
            provider=provider,
            top_n=int(top_n),
            cache_enabled=bool(settings_meta["cache_enabled"]),
            corpus_cache_token=settings_meta["corpus_cache_token"],
            score_calibration_enabled=bool(settings_meta["score_calibration_enabled"]),
            score_calibration_alpha=float(settings_meta["score_calibration_alpha"]),
            score_calibration_stats=score_calibration_stats,
        )
        return _apply_single_result(
            result=result,
            single_result=single_result,
            score_calibration_stats=score_calibration_stats,
        )
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_run_post_rerank_stage", exc)
        result["post_rerank_error"] = str(exc)[:200]
        result["post_rerank_skip_reason"] = "error"
        result["post_rerank_used"] = False
        result["post_rerank_score_calibration_used"] = bool(score_calibration_stats["used"])
        return result
