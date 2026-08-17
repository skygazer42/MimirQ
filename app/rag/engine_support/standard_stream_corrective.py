"""Corrective retrieval subphases for standard RAG streaming."""

import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.engine_support.standard_stream_state import StandardStreamState


def _corrective_retry_needed(runtime: StandardStreamState) -> bool:
    return bool(
        runtime.data.corrective_enabled
        and runtime.data.abstain_triggered
        and runtime.data.corrective_attempt_count < runtime.data.corrective_max_attempts
    )


def _record_generated_retry_queries(runtime: StandardStreamState) -> None:
    if not runtime.data.retry_multi_queries:
        return
    runtime.data.multi_queries = list(runtime.data.retry_multi_queries)
    runtime.data.multi_query_used = True
    runtime.data.multi_query_elapsed = max(
        float(runtime.data.multi_query_elapsed or 0.0),
        float(runtime.data.retry_mq_elapsed or 0.0),
    )
    runtime.data.multi_query_model_used = runtime.data.retry_mq_model_used or runtime.data.multi_query_model_used
    runtime.data.multi_query_parse_meta = dict(runtime.data.retry_mq_parse_meta or {})


async def _prepare_retry_queries(runtime: StandardStreamState) -> None:
    runtime.data.retry_profile_norm = runtime.data.corrective_second_profile
    runtime.data.retry_score_threshold = (
        0.0
        if runtime.module.is_recall_first_profile(runtime.data.retry_profile_norm)
        else runtime.data.score_threshold_used
    )
    runtime.data.retry_multi_queries = list(runtime.data.multi_queries)
    if runtime.data.corrective_second_enable_mq and not runtime.data.retry_multi_queries:
        (
            runtime.data.retry_multi_queries,
            runtime.data.retry_mq_elapsed,
            runtime.data.retry_mq_model_used,
            runtime.data.retry_mq_parse_meta,
        ) = await runtime.engine._generate_multi_queries(
            query=runtime.data.query_for_retrieval,
            llm=runtime.data.llm,
            enabled=True,
            count=int(runtime.data.corrective_second_mq_count or 0),
            temperature=float(runtime.data.mq_temp or 0.0),
            max_chars=int(runtime.data.mq_max_chars or 0),
        )
        _record_generated_retry_queries(runtime)
    runtime.data.retry_retriever_update = dict(runtime.data.retriever_update)
    runtime.data.retry_retriever_update["retrieval_profile"] = runtime.data.retry_profile_norm
    runtime.data.retry_retriever_update["score_threshold"] = runtime.data.retry_score_threshold
    if runtime.module.is_recall_first_profile(runtime.data.retry_profile_norm):
        runtime.data.retry_retriever_update.update(
            {
                "dedup_enabled": False,
                "max_chunks_per_doc": 0,
                "max_chunks_per_page": 0,
                "min_distinct_docs": 0,
            }
        )
    runtime.data.retry_retriever = runtime.module.hybrid_retriever.model_copy(
        update=runtime.data.retry_retriever_update
    )
    runtime.data.retry_queries = list(runtime.data.retrieval_queries_base)
    runtime.data.retry_queries.extend(("mq", query) for query in runtime.data.retry_multi_queries)
    runtime.data.retry_queries = runtime.engine._dedup_retrieval_queries(runtime.data.retry_queries)
    runtime.data.retry_docs_by_query = []
    runtime.data.retry_docs_by_query_kinds = []
    runtime.data.retry_errors = []
    runtime.data.retry_per_query = []


def _retry_retriever_for_kind(runtime: StandardStreamState, kind: str) -> Any:
    if kind == "main":
        return runtime.data.retry_retriever
    if kind == "hyde":
        return runtime.data.retry_retriever.model_copy(
            update={
                "enable_reranker": False,
                "retrieval_mode": "vector",
                "enable_weight_rerank": False,
            }
        )
    return runtime.data.retry_retriever.model_copy(update={"enable_reranker": False})


def _record_retry_result(
    runtime: StandardStreamState,
    *,
    kind: str,
    query: str,
    docs: list[Document],
    error: str | None,
    elapsed: float,
    debug: dict[str, Any] | None,
) -> None:
    runtime.data.retry_per_query.append(
        {
            "kind": kind,
            "query_chars": len(query or ""),
            "query_tokens": runtime.module.num_tokens_from_string(query or ""),
            "elapsed_sec": round(elapsed, 3),
            "ok": error is None,
            "retriever_debug": debug,
        }
    )
    runtime.data.retry_docs_by_query_kinds.append(kind)
    runtime.data.retry_docs_by_query.append(runtime.engine._annotate_docs_with_role(docs or [], kind))


async def _execute_retry_queries(
    runtime: StandardStreamState,
) -> AsyncGenerator[dict[str, Any], None]:
    retry_start = time.time()
    for kind, query in runtime.data.retry_queries:
        retriever = _retry_retriever_for_kind(runtime, kind)
        kind, docs, error, elapsed, debug = await runtime.data.run_one(kind, query, retriever)
        _record_retry_result(
            runtime,
            kind=kind,
            query=query,
            docs=docs,
            error=error,
            elapsed=elapsed,
            debug=debug,
        )
        if error:
            runtime.data.retry_errors.append(f"{kind}:{error[:160]}")
            if kind == "main":
                yield {"type": "error", "data": {"message": f"retrieval failed: {error}"}}
    runtime.data.retrieval_elapsed += time.time() - retry_start
    runtime.data.retrieval_errors = runtime.data.retry_errors
    runtime.data.retrieval_per_query = runtime.data.retry_per_query
    runtime.data.profile_norm = runtime.data.retry_profile_norm
    runtime.data.retrieval_profile = runtime.data.retry_profile_norm


def _initialize_retry_fusion(runtime: StandardStreamState) -> None:
    runtime.data.retry_mq_diversify_enabled = bool(getattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", False)) and bool(
        runtime.data.corrective_second_enable_mq or runtime.data.multi_query_used
    )
    try:
        retry_budget = int(getattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 0) or 0)
    except Exception:
        retry_budget = 0
    runtime.data.mq_diversify_budget = max(0, min(retry_budget, int(runtime.data.top_k or 0)))
    runtime.data.mq_diversify_used = False
    runtime.data.mq_diversify_selected_mq = 0
    runtime.data.mq_diversify_selected_non_mq = 0
    runtime.data.mq_diversify_fill_from_fused = 0


def _fuse_retry_doc_lists(runtime: StandardStreamState, doc_lists: list[list[Document]]) -> list[Document]:
    if len(doc_lists) == 1:
        return doc_lists[0] or []
    return runtime.engine.fuse_docs_rrf(
        doc_lists,
        rrf_k=settings.RETRIEVAL_RRF_K,
        meta_prefix="query_expansion",
    )


def _partition_retry_docs(runtime: StandardStreamState) -> None:
    runtime.data.mq_lists = []
    runtime.data.non_mq_lists = []
    pairs = zip(
        runtime.data.retry_docs_by_query_kinds,
        runtime.data.retry_docs_by_query,
        strict=False,
    )
    for kind, docs in pairs:
        if kind == "mq":
            runtime.data.mq_lists.append(docs or [])
        else:
            runtime.data.non_mq_lists.append(docs or [])


def _select_retry_non_mq_docs(runtime: StandardStreamState) -> None:
    for doc in runtime.data.docs_non_mq:
        key = runtime.engine._doc_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        if len(runtime.data.selected) >= runtime.data.want_non_mq:
            break
    runtime.data.mq_diversify_selected_non_mq = len(runtime.data.selected)


def _select_retry_mq_docs(runtime: StandardStreamState) -> None:
    added = 0
    for doc in runtime.data.docs_mq:
        if added >= runtime.data.want_mq:
            break
        key = runtime.engine._doc_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        added += 1
    runtime.data.mq_diversify_selected_mq = added


def _fill_retry_fused_docs(runtime: StandardStreamState) -> None:
    for doc in runtime.data.docs_fused_all:
        if len(runtime.data.selected) >= int(runtime.data.top_k or 0):
            break
        key = runtime.engine._doc_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        runtime.data.mq_diversify_fill_from_fused += 1


def _diversify_retry_docs(runtime: StandardStreamState) -> None:
    runtime.data.mq_diversify_used = True
    runtime.data.docs_non_mq = _fuse_retry_doc_lists(runtime, runtime.data.non_mq_lists)
    runtime.data.docs_mq = _fuse_retry_doc_lists(runtime, runtime.data.mq_lists)
    runtime.data.want_non_mq = max(0, int(runtime.data.top_k or 0) - runtime.data.mq_diversify_budget)
    runtime.data.want_mq = runtime.data.mq_diversify_budget
    runtime.data.selected = []
    runtime.data.selected_keys = set()
    _select_retry_non_mq_docs(runtime)
    _select_retry_mq_docs(runtime)
    _fill_retry_fused_docs(runtime)
    runtime.data.docs = runtime.data.selected


def _fuse_retry_docs(runtime: StandardStreamState) -> None:
    if len(runtime.data.retry_docs_by_query) <= 1:
        runtime.data.docs = runtime.data.retry_docs_by_query[0] if runtime.data.retry_docs_by_query else []
        return
    runtime.data.docs_fused_all = _fuse_retry_doc_lists(runtime, runtime.data.retry_docs_by_query)
    if not (runtime.data.retry_mq_diversify_enabled and runtime.data.mq_diversify_budget > 0):
        runtime.data.docs = runtime.data.docs_fused_all
        return
    _partition_retry_docs(runtime)
    if not (runtime.data.mq_lists and runtime.data.non_mq_lists):
        runtime.data.docs = runtime.data.docs_fused_all
        return
    _diversify_retry_docs(runtime)


def _merge_baseline_retry_docs(runtime: StandardStreamState) -> None:
    if not runtime.data.baseline_retry_docs:
        return
    merged_docs = []
    merged_keys = set()
    for doc in (runtime.data.docs or []) + runtime.data.baseline_retry_docs:
        key = runtime.engine._doc_key(doc)
        if key in merged_keys:
            continue
        merged_keys.add(key)
        merged_docs.append(doc)
    runtime.data.docs = merged_docs[: max(0, int(runtime.data.top_k or 0))] if merged_docs else []


def _apply_corrective_retrieval_rail(runtime: StandardStreamState) -> None:
    runtime.data.retrieval_rail_enabled = settings.RAG_RETRIEVAL_RAIL_ENABLED
    runtime.data.retrieval_rail_meta = {
        "enabled": bool(runtime.data.retrieval_rail_enabled),
        "used": False,
        "blocked_docs": 0,
        "masked_docs": 0,
    }
    if not (runtime.data.retrieval_rail_enabled and runtime.data.docs):
        return
    try:
        from app.rag.safety.retrieval_rail import apply_retrieval_rail

        rail_result = apply_retrieval_rail(
            runtime.data.docs,
            mask_pii=settings.RAG_RETRIEVAL_RAIL_MASK_PII,
            pii_mask=settings.RAG_RETRIEVAL_RAIL_PII_MASK,
        )
        runtime.data.docs = list(rail_result.get("docs") or [])
        meta = dict(rail_result.get("meta") or {})
        runtime.data.retrieval_rail_meta = {
            "enabled": True,
            "used": bool(meta.get("used")),
            "blocked_docs": int(meta.get("blocked_docs") or 0),
            "masked_docs": int(meta.get("masked_docs") or 0),
        }
    except Exception as exc:  # noqa: BLE001
        runtime.module.logger.warning("Retrieval rail failed open: %s", str(exc)[:160])
        runtime.data.retrieval_rail_meta = {
            "enabled": True,
            "used": False,
            "blocked_docs": 0,
            "masked_docs": 0,
            "error": str(exc)[:160],
        }


def _filter_evidence_span_citations(runtime: StandardStreamState) -> None:
    runtime.data.evidence_span_missing_citations = 0
    if not (runtime.data.evidence_span_strict_enabled and runtime.data.citations):
        return
    filtered_citations = []
    for item in runtime.data.citations:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("evidence_start_char"))
            end = int(item.get("evidence_end_char"))
        except Exception:
            start = None
            end = None
        if start is None or end is None or end <= start:
            runtime.data.evidence_span_missing_citations += 1
            continue
        filtered_citations.append(item)
    runtime.data.citations = filtered_citations


def _rebuild_retry_citations(runtime: StandardStreamState) -> None:
    runtime.data.citations = runtime.module.build_citations_from_docs(
        runtime.data.docs,
        retrieval_elapsed_sec=runtime.data.retrieval_elapsed,
        retrieval_mode=runtime.data.mode_used,
        query=runtime.data.query_for_retrieval,
    )
    _filter_evidence_span_citations(runtime)


def _top_relevance_score(citations: list[dict[str, Any]]) -> float:
    if not citations:
        return 0.0
    try:
        return max(
            float(
                (
                    citation.get("relevance_score")
                    if citation.get("relevance_score") is not None
                    else citation.get("retrieval_score")
                )
                or 0.0
            )
            for citation in citations
        )
    except Exception:
        return 0.0


def _evaluate_retry_abstention(runtime: StandardStreamState) -> None:
    runtime.data.top_rel = _top_relevance_score(runtime.data.citations)
    runtime.data.abstain_triggered = False
    runtime.data.abstain_reason = None
    if not runtime.data.abstain_enabled:
        return
    min_citations = max(0, int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0))
    min_top_relevance = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)
    if min_citations > 0 and len(runtime.data.citations) < min_citations:
        runtime.data.abstain_triggered = True
        runtime.data.abstain_reason = "citations_lt_min"
    elif min_top_relevance > 0 and runtime.data.top_rel < min_top_relevance:
        runtime.data.abstain_triggered = True
        runtime.data.abstain_reason = "top_relevance_lt_min"


def _retry_info_event(runtime: StandardStreamState) -> dict[str, Any] | None:
    return runtime.engine._build_retrieval_info_event(
        attempt=runtime.data.corrective_attempt_count,
        query_count=len(runtime.data.retry_queries),
        docs_count=len(runtime.data.docs),
        citations_count=len(runtime.data.citations),
        abstain_triggered=runtime.data.abstain_triggered,
        retrieval_profile=runtime.data.profile_norm or None,
    )


def _record_corrective_attempt(runtime: StandardStreamState) -> None:
    runtime.data.corrective_attempts.append(
        {
            "attempt": int(runtime.data.corrective_attempt_count),
            "retrieval_profile": runtime.data.profile_norm or None,
            "query_count": int(len(runtime.data.retry_queries)),
            "docs_count": int(len(runtime.data.docs)),
            "citations_count": int(len(runtime.data.citations)),
            "abstain_triggered": bool(runtime.data.abstain_triggered),
            "top_relevance_score": round(float(runtime.data.top_rel or 0.0), 3),
        }
    )


async def stream_corrective_retrieval(
    runtime: StandardStreamState,
) -> AsyncGenerator[dict[str, Any], None]:
    if not _corrective_retry_needed(runtime):
        return
    if "abstain" not in runtime.data.corrective_reason_codes:
        runtime.data.corrective_reason_codes.append("abstain")
    runtime.data.corrective_used = True
    runtime.data.corrective_attempt_count += 1
    runtime.data.baseline_retry_docs = list(runtime.data.docs or [])
    retry_message = "检索证据偏弱，正在进行一次 recall-first 重试..."
    yield {"type": "event", "data": {"message": retry_message}}
    retry_status = runtime.engine._build_stream_status_event(
        stage="retrieval",
        state="retrying",
        message=retry_message,
        attempt=runtime.data.corrective_attempt_count,
        max_attempts=runtime.data.corrective_max_attempts,
    )
    if retry_status is not None:
        yield retry_status
    await _prepare_retry_queries(runtime)
    async with aclosing(_execute_retry_queries(runtime)) as retry_events:
        async for event in retry_events:
            yield event
    _initialize_retry_fusion(runtime)
    _fuse_retry_docs(runtime)
    runtime.data.docs = runtime.data.docs[: max(0, int(runtime.data.top_k or 0))] if runtime.data.docs else []
    _merge_baseline_retry_docs(runtime)
    _apply_corrective_retrieval_rail(runtime)
    _rebuild_retry_citations(runtime)
    yield {"type": "citations", "data": runtime.data.citations}
    _evaluate_retry_abstention(runtime)
    retry_info = _retry_info_event(runtime)
    if retry_info is not None:
        yield retry_info
    _record_corrective_attempt(runtime)


__all__ = ["stream_corrective_retrieval"]
