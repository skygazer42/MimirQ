from collections.abc import Callable
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.reranker.types import RerankCandidate


def _annotate_retrieval_score(meta: dict[str, Any]) -> None:
    base = meta.get("retrieval_score")
    if base is None:
        base = meta.get("score", 0.0)
    try:
        meta["retrieval_score"] = float(base or 0.0)
    except (TypeError, ValueError, AttributeError):
        meta["retrieval_score"] = 0.0


def _build_reranked_document(
    *,
    doc: Document,
    meta: dict[str, Any],
) -> Document:
    return Document(
        page_content=doc.page_content,
        metadata=meta,
        id=getattr(doc, "id", None) or meta.get("chunk_id"),
    )


def build_reranked_prefix(
    *,
    docs_prefix: list[Document],
    id_to_doc: dict[str, Document],
    rerank_result: Any,
    provider: str,
    elapsed_sec: float,
    model_used: str | None,
    annotate_scores: bool,
    doc_key_fn: Callable[[Document], str],
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
            _annotate_retrieval_score(meta)
            if rid in rerank_result.score_map:
                meta["rerank_score"] = float(rerank_result.score_map[rid])
                meta["score"] = float(rerank_result.score_map[rid])
            meta["reranker_provider"] = provider
            meta["rerank_elapsed_sec"] = rerank_elapsed
            meta["rerank_model_used"] = model_used
        ordered_prefix.append(_build_reranked_document(doc=doc, meta=meta))

    for doc in docs_prefix:
        rid = doc_key_fn(doc)
        if rid in used:
            continue
        meta = dict(doc.metadata or {})
        if annotate_scores:
            _annotate_retrieval_score(meta)
            meta.setdefault("reranker_provider", provider)
            meta.setdefault("rerank_elapsed_sec", rerank_elapsed)
            meta.setdefault("rerank_model_used", model_used)
        ordered_prefix.append(_build_reranked_document(doc=doc, meta=meta))
    return ordered_prefix


def post_rerank_settings(
    state: dict[str, Any],
    *,
    cache_backend_fn: Callable[[], Any],
    corpus_cache_token_fn: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any]:
    cache_enabled = bool(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", False))
    try:
        calibration_alpha = float(getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA", 0.7) or 0.7)
    except (TypeError, ValueError, AttributeError):
        calibration_alpha = 0.7
    calibration_alpha = min(1.0, max(0.0, float(calibration_alpha)))
    return {
        "enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False)),
        "pipeline_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", False)),
        "pipeline_raw": getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", ""),
        "provider": str(getattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "") or "ltr").strip().lower(),
        "top_n": int(getattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 0) or 0),
        "cache_enabled": cache_enabled,
        "cache_backend": cache_backend_fn(),
        "corpus_cache_token": corpus_cache_token_fn(state),
        "score_calibration_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED", False)),
        "score_calibration_alpha": calibration_alpha,
    }


def run_post_rerank_single_mode(
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
    build_candidates_fn: Callable[..., tuple[list[RerankCandidate], dict[str, Document]]],
    get_cached_result_fn: Callable[..., tuple[Any, str | None, bool, int, int]],
    execute_post_rerank_fn: Callable[..., tuple[Any, float]],
    build_reranked_prefix_fn: Callable[..., list[Document]],
    calibrate_prefix_fn: Callable[..., tuple[list[Document], bool]],
) -> dict[str, Any]:
    governed_n = min(int(top_n), len(docs or []))
    governed_n = max(governed_n, int(top_k or 0))
    governed_n = min(governed_n, len(docs or []))
    candidates, id_to_doc = build_candidates_fn(docs, limit=int(governed_n))
    result: dict[str, Any] = {
        "docs": list(docs or []),
        "post_rerank_used": False,
        "post_rerank_provider": provider,
        "post_rerank_model_used": None,
        "post_rerank_candidates_n": int(governed_n),
        "post_rerank_elapsed": 0.0,
        "post_rerank_cache_hits": 0,
        "post_rerank_cache_misses": 0,
        "post_rerank_score_calibration_used": False,
        "post_rerank_skip_reason": "no_candidates",
    }
    if not candidates:
        return result

    cached, cache_key, _, cache_hits, cache_misses = get_cached_result_fn(
        state=state,
        provider=provider,
        top_n=int(governed_n),
        query_for_retrieval=query_for_retrieval,
        candidates=candidates,
        cache_enabled=cache_enabled,
        corpus_cache_token=corpus_cache_token,
    )
    rerank_result, elapsed_sec = execute_post_rerank_fn(
        state=state,
        provider=provider,
        top_n=int(governed_n),
        query_for_retrieval=query_for_retrieval,
        candidates=candidates,
        cache_enabled=cache_enabled,
        cache_key=cache_key,
        cached_result=cached,
    )
    model_used = rerank_result.model_used
    reranker_provider = rerank_result.provider or provider
    ordered = build_reranked_prefix_fn(
        docs_prefix=list((docs or [])[:governed_n]),
        id_to_doc=id_to_doc,
        rerank_result=rerank_result,
        provider=reranker_provider,
        elapsed_sec=elapsed_sec,
        model_used=model_used,
        annotate_scores=True,
    )
    ordered, score_calibration_used = calibrate_prefix_fn(
        ordered,
        enabled=bool(score_calibration_enabled),
        alpha=float(score_calibration_alpha),
        stats=score_calibration_stats,
    )
    return {
        "docs": ordered + list((docs or [])[governed_n:]),
        "post_rerank_used": True,
        "post_rerank_provider": reranker_provider,
        "post_rerank_model_used": model_used,
        "post_rerank_candidates_n": int(governed_n),
        "post_rerank_elapsed": float(elapsed_sec),
        "post_rerank_cache_hits": int(cache_hits),
        "post_rerank_cache_misses": int(cache_misses),
        "post_rerank_score_calibration_used": bool(score_calibration_used),
        "post_rerank_skip_reason": None,
    }


def _stage_top_n(
    *,
    stage: dict[str, Any],
    previous_n: int | None,
    top_n: int,
    docs_count: int,
) -> int:
    try:
        stage_n = int(stage.get("top_n") or 0)
    except (TypeError, ValueError, AttributeError):
        stage_n = 0
    if stage_n <= 0:
        stage_n = int(previous_n or top_n)
    if previous_n is not None:
        stage_n = min(int(stage_n), int(previous_n))
    return min(int(stage_n), docs_count)


def _pipeline_noop_result(
    *,
    docs: list[Document],
    stages: list[dict[str, Any]],
    cache_hits: int,
    cache_misses: int,
) -> dict[str, Any]:
    return {
        "docs": list(docs or []),
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
            "top_n": int(stage_n),
            "candidates": int(candidates_count),
            "elapsed_sec": round(float(elapsed_sec), 3),
            "model_used": model_used,
            "cache_hit": bool(cache_hit),
        }
    )


def run_post_rerank_pipeline_mode(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_n: int,
    pipeline: list[dict[str, Any]],
    cache_enabled: bool,
    corpus_cache_token: str | None,
    score_calibration_enabled: bool,
    score_calibration_alpha: float,
    score_calibration_stats: dict[str, Any],
    build_candidates_fn: Callable[..., tuple[list[RerankCandidate], dict[str, Document]]],
    get_cached_result_fn: Callable[..., tuple[Any, str | None, bool, int, int]],
    execute_post_rerank_fn: Callable[..., tuple[Any, float]],
    build_reranked_prefix_fn: Callable[..., list[Document]],
    calibrate_prefix_fn: Callable[..., tuple[list[Document], bool]],
) -> dict[str, Any]:
    docs_work: list[Document] = list(docs or [])
    total_elapsed = 0.0
    previous_n: int | None = None
    final_provider: str | None = None
    final_model_used: str | None = None
    final_n = 0
    stages: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0

    for index, stage in enumerate(pipeline):
        stage_provider = str(stage.get("provider") or "").strip().lower()
        if not stage_provider or stage_provider in {"none", "off", "false", "0"}:
            continue

        stage_n = _stage_top_n(
            stage=stage,
            previous_n=previous_n,
            top_n=top_n,
            docs_count=len(docs_work),
        )
        if stage_n <= 0:
            continue

        candidates, id_to_doc = build_candidates_fn(docs_work, limit=int(stage_n))
        if not candidates:
            continue

        cached, cache_key, cache_hit, hit_delta, miss_delta = get_cached_result_fn(
            state=state,
            provider=stage_provider,
            top_n=int(stage_n),
            query_for_retrieval=query_for_retrieval,
            candidates=candidates,
            cache_enabled=cache_enabled,
            corpus_cache_token=corpus_cache_token,
        )
        cache_hits += int(hit_delta)
        cache_misses += int(miss_delta)
        rerank_result, elapsed_i = execute_post_rerank_fn(
            state=state,
            provider=stage_provider,
            top_n=int(stage_n),
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
            final_n = int(stage_n)

        ordered_prefix = build_reranked_prefix_fn(
            docs_prefix=list(docs_work[:stage_n]),
            id_to_doc=id_to_doc,
            rerank_result=rerank_result,
            provider=used_provider,
            elapsed_sec=total_elapsed,
            model_used=rerank_result.model_used,
            annotate_scores=bool(is_final),
        )
        if is_final:
            ordered_prefix, score_calibration_used = calibrate_prefix_fn(
                ordered_prefix,
                enabled=bool(score_calibration_enabled),
                alpha=float(score_calibration_alpha),
                stats=score_calibration_stats,
            )
        else:
            score_calibration_used = False
        docs_work = ordered_prefix + list(docs_work[stage_n:])
        previous_n = int(stage_n)
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
        "post_rerank_candidates_n": int(final_n),
        "post_rerank_elapsed": float(total_elapsed),
        "post_rerank_cache_hits": int(cache_hits),
        "post_rerank_cache_misses": int(cache_misses),
        "post_rerank_score_calibration_used": bool(score_calibration_stats.get("used")),
        "post_rerank_skip_reason": None,
    }


def _initial_post_rerank_result(
    *,
    docs: list[Document],
    settings_meta: dict[str, Any],
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "docs": list(docs or []),
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
    result["post_rerank_score_calibration_used"] = bool(pipeline_result.get("post_rerank_score_calibration_used"))
    if not bool(pipeline_result.get("post_rerank_used")) and result.get("post_rerank_skip_reason") is None:
        result["post_rerank_skip_reason"] = "pipeline_noop"
    return bool(pipeline_result.get("post_rerank_used"))


def _apply_single_result(
    *,
    result: dict[str, Any],
    single_result: dict[str, Any],
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    result["docs"] = list(single_result.get("docs") or result.get("docs") or [])
    result["post_rerank_used"] = bool(single_result.get("post_rerank_used"))
    result["post_rerank_provider"] = single_result.get("post_rerank_provider")
    result["post_rerank_model_used"] = single_result.get("post_rerank_model_used")
    result["post_rerank_candidates_n"] = int(single_result.get("post_rerank_candidates_n") or 0)
    result["post_rerank_elapsed"] = float(single_result.get("post_rerank_elapsed") or 0.0)
    result["post_rerank_cache_hits"] = int(result["post_rerank_cache_hits"]) + int(
        single_result.get("post_rerank_cache_hits") or 0
    )
    result["post_rerank_cache_misses"] = int(result["post_rerank_cache_misses"]) + int(
        single_result.get("post_rerank_cache_misses") or 0
    )
    single_skip_reason = single_result.get("post_rerank_skip_reason")
    if single_skip_reason is not None:
        result["post_rerank_skip_reason"] = single_skip_reason
    if single_result.get("post_rerank_score_calibration_used") is not None:
        score_calibration_stats["used"] = bool(single_result.get("post_rerank_score_calibration_used"))
    result["post_rerank_score_calibration_used"] = bool(score_calibration_stats.get("used"))
    result["post_rerank_score_calibration_stats"] = score_calibration_stats
    return result


def run_post_rerank_stage(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_k: int,
    settings_meta: dict[str, Any],
    pipeline_summary_fn: Callable[[Any], list[dict[str, Any]]],
    pipeline_mode_fn: Callable[..., dict[str, Any]],
    single_mode_fn: Callable[..., dict[str, Any]],
    fallback_logger_fn: Callable[[str, Exception], None],
) -> dict[str, Any]:
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
    if not settings_meta["enabled"] and not docs:
        return result
    if settings_meta["enabled"] and not docs:
        result["post_rerank_skip_reason"] = "no_candidates"
        return result
    if not settings_meta["enabled"]:
        return result

    provider = str(settings_meta["provider"] or "")
    if provider in {"none", "off", "false", "0"}:
        result["post_rerank_skip_reason"] = "provider_off"
        return result

    top_n = int(settings_meta["top_n"] or 0)
    if top_n <= 0:
        top_n = len(docs or [])
    top_n = min(int(top_n), len(docs or []))

    try:
        pipeline: list[dict[str, Any]] = []
        if settings_meta["pipeline_enabled"]:
            pipeline = pipeline_summary_fn(settings_meta["pipeline_raw"])
            result["post_rerank_pipeline"] = pipeline
        if pipeline:
            pipeline_result = pipeline_mode_fn(
                state=state,
                docs=list(docs or []),
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

        single_result = single_mode_fn(
            state=state,
            docs=list(result.get("docs") or docs or []),
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
        fallback_logger_fn("_run_post_rerank_stage", exc)
        result["post_rerank_error"] = str(exc)[:200]
        result["post_rerank_skip_reason"] = "error"
        result["post_rerank_used"] = False
        result["post_rerank_score_calibration_used"] = bool(score_calibration_stats.get("used"))
        return result
