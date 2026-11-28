"""Follow evidence gaps and apply the configured fallback retrieval."""

import time
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.hashing import stable_hash
from app.rag.retrieval.evidence.citations import build_citations_from_docs
from app.rag.retrieval.evidence.gaps import detect_evidence_gap
from app.rag.retrieval.planning.followup import build_contextual_followup_query
from app.rag.retrieval.ranking.anchors import _apply_metadata_exact_anchor_doc_ordering
from app.rag.retrieval.ranking.fusion import annotate_documents_with_role
from app.rag.retrieval.recall.retriever import hybrid_retriever
from app.rag.retrieval.results import _log_orchestrator_fallback, document_key
from app.rag.retrieval.stages.search import QueryInvocationRecordInput, build_query_invocation_record
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.rag.tracing.retrieval_debug import _sanitize_retriever_debug
from app.storage.bm25.milvus import BM25IndexNotReadyError


def _filter_strict_span_citations(
    items: list[dict[str, Any]],
    *,
    enabled: bool,
) -> tuple[list[dict[str, Any]], int]:
    if not enabled or not items:
        return items, 0
    filtered_items: list[dict[str, Any]] = []
    missing_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        start = item.get("evidence_start_char")
        end = item.get("evidence_end_char")
        try:
            start_i = int(start) if start is not None else None
            end_i = int(end) if end is not None else None
        except (TypeError, ValueError):
            start_i = None
            end_i = None
        if start_i is None or end_i is None or end_i <= start_i:
            missing_count += 1
            continue
        filtered_items.append(item)
    return filtered_items, missing_count


def _contextual_evidence_gap(ctx: RetrievalRuntimeState, citations: list[dict[str, Any]]) -> dict[str, Any]:
    return detect_evidence_gap(
        citations=citations,
        required_source_keys=(ctx.must_recall_expected_source_keys if ctx.must_recall_enabled else []),
        required_anchor_fields=(ctx.must_recall_required_anchor_fields if ctx.must_recall_enabled else []),
        min_citations=1,
    )


def _extend_unique(target: list[str], values: list[str], *, limit: int | None = None) -> None:
    for value in values:
        if value not in target:
            target.append(value)
            if limit is not None and len(target) >= limit:
                break


def _contextual_query_spec(
    ctx: RetrievalRuntimeState,
    spec: dict[str, Any],
    hop_diag: dict[str, Any],
) -> tuple[str, list[str]]:
    reason_codes = spec["reason_codes"][:8]
    hop_diag["reason_codes"] = reason_codes
    _extend_unique(ctx.contextual_followup_reason_codes, reason_codes)
    _extend_unique(ctx.iterative_pass_reason_codes, reason_codes)
    selected_terms = spec["selected_terms"]
    _extend_unique(ctx.contextual_followup_selected_terms, selected_terms, limit=10)
    query = spec["query"].strip()
    if query:
        ctx.contextual_followup_followup_query = query
        ctx.contextual_followup_query_hash = stable_hash(query)
        hop_diag["query_hash"] = ctx.contextual_followup_query_hash
    return query, reason_codes


def _invoke_contextual_followup(
    ctx: RetrievalRuntimeState,
    *,
    query: str,
    hop: int,
) -> list[Document]:
    started = time.time()
    docs: list[Document] = []
    error: str | None = None
    try:
        retriever_update = dict(ctx.retriever_update)
        retriever_update.update(
            {
                "retrieval_mode": str(ctx.contextual_followup_mode),
                "k": int(ctx.contextual_followup_top_k),
                "enable_reranker": False,
            }
        )
        retriever_obj = hybrid_retriever.model_copy(update=retriever_update)
        docs = annotate_documents_with_role(
            retriever_obj.invoke(query) or [],
            "contextual_followup",
        )
        debug = getattr(retriever_obj, "_last_debug_metrics", None)
        ctx.contextual_followup_retriever_debug = _sanitize_retriever_debug(debug if isinstance(debug, dict) else None)
    except BM25IndexNotReadyError:
        raise
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        error = str(exc)[:200]
    elapsed = max(0.0, float(time.time() - started))
    ctx.contextual_followup_elapsed += elapsed
    ctx.retrieval_elapsed += elapsed
    record = build_query_invocation_record(
        QueryInvocationRecordInput(
            kind="contextual_followup",
            query=query,
            docs=docs,
            error=error,
            elapsed_sec=elapsed,
            retriever_debug=ctx.contextual_followup_retriever_debug,
            hop=hop,
        )
    )
    ctx.retrieval_per_query.append(record.per_query_item)
    if record.error_entry:
        ctx.contextual_followup_error = error
        ctx.retrieval_errors.append(record.error_entry)
    return docs


def _merge_contextual_docs(current: list[Document], incoming: list[Document]) -> tuple[list[Document], int]:
    merged = list(current)
    seen_keys = {key for doc in merged if doc is not None and (key := document_key(doc)) is not None}
    added = 0
    for doc in incoming:
        if doc is None:
            continue
        key = document_key(doc)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        merged.append(doc)
        added += 1
    return merged, added


def _apply_contextual_followup_docs(
    ctx: RetrievalRuntimeState,
    *,
    docs: list[Document],
    citations_before: list[dict[str, Any]],
    hop_diag: dict[str, Any],
    reason_codes: list[str],
) -> tuple[int, int]:
    if not docs:
        return 0, 0
    merged_docs, added_docs = _merge_contextual_docs(list(ctx.docs), docs)
    if added_docs <= 0:
        hop_diag["reason_codes"] = reason_codes + ["no_new_docs"]
        _extend_unique(ctx.iterative_pass_reason_codes, ["no_new_docs"])
        return 0, 0
    ctx.docs = merged_docs
    citations_after = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    added_citations = max(0, len(citations_after) - len(citations_before))
    ctx.contextual_followup_added_docs += added_docs
    ctx.contextual_followup_added_citations += added_citations
    ctx.contextual_followup_used = True
    ctx.iterative_pass_gap = _contextual_evidence_gap(ctx, citations_after)
    hop_diag["gap_after"] = dict(ctx.iterative_pass_gap)
    if not ctx.iterative_pass_gap["has_gap"]:
        _extend_unique(ctx.iterative_pass_reason_codes, ["gap_closed"])
    return added_docs, added_citations


def _run_contextual_followup_hop(ctx: RetrievalRuntimeState, hop: int) -> bool:
    citations_before = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    ctx.iterative_pass_gap = _contextual_evidence_gap(ctx, citations_before)
    hop_diag: dict[str, Any] = {
        "hop": hop,
        "attempted": False,
        "used": False,
        "query_hash": None,
        "added_docs": 0,
        "added_citations": 0,
        "reason_codes": [],
        "gap_before": dict(ctx.iterative_pass_gap),
        "gap_after": None,
    }
    spec = build_contextual_followup_query(
        query=ctx.query_for_retrieval,
        docs=list(ctx.docs),
        evidence_gap=ctx.iterative_pass_gap,
        max_docs=int(ctx.contextual_followup_max_docs),
        max_terms=int(ctx.contextual_followup_max_terms),
        min_term_chars=int(ctx.contextual_followup_min_term_chars),
        max_query_chars=int(ctx.contextual_followup_max_query_chars),
    )
    query, reason_codes = _contextual_query_spec(ctx, spec, hop_diag)
    if not (spec["used"] and query):
        hop_diag["reason_codes"] = reason_codes or ["planner_not_used"]
        ctx.iterative_pass_hops.append(hop_diag)
        _extend_unique(ctx.iterative_pass_reason_codes, ["planner_not_used"])
        return False
    ctx.contextual_followup_attempted = True
    hop_diag["attempted"] = True
    docs = _invoke_contextual_followup(ctx, query=query, hop=hop)
    added_docs, added_citations = _apply_contextual_followup_docs(
        ctx,
        docs=docs,
        citations_before=citations_before,
        hop_diag=hop_diag,
        reason_codes=reason_codes,
    )
    hop_diag["used"] = added_docs > 0
    hop_diag["added_docs"] = added_docs
    hop_diag["added_citations"] = added_citations
    ctx.iterative_pass_hops.append(hop_diag)
    return added_docs > 0 and ctx.iterative_pass_gap["has_gap"]


def _run_retrieval_contextual_followup_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    if not ctx.contextual_followup_enabled or not ctx.docs:
        return None
    iterative_start = time.time()
    for hop in range(1, int(ctx.contextual_followup_max_hops) + 1):
        elapsed_ms = (time.time() - iterative_start) * 1000.0
        if ctx.contextual_followup_latency_budget_ms > 0.0 and elapsed_ms >= ctx.contextual_followup_latency_budget_ms:
            ctx.iterative_pass_reason_codes.append("latency_budget_exhausted")
            break
        if not _run_contextual_followup_hop(ctx, hop):
            break
    return None


def _invoke_hard_fallback(ctx: RetrievalRuntimeState) -> list[Document]:
    started = time.time()
    docs: list[Document] = []
    error: str | None = None
    try:
        retriever_update = dict(ctx.retriever_update)
        retriever_update.update(
            {
                "retrieval_mode": ctx.hard_fallback_mode,
                "k": int(ctx.hard_fallback_top_k),
                "enable_reranker": False,
            }
        )
        retriever_obj = hybrid_retriever.model_copy(update=retriever_update)
        docs = annotate_documents_with_role(
            retriever_obj.invoke(ctx.query_for_retrieval) or [],
            "hard_fallback",
        )
        debug = getattr(retriever_obj, "_last_debug_metrics", None)
        ctx.hard_fallback_retriever_debug = _sanitize_retriever_debug(debug if isinstance(debug, dict) else None)
    except BM25IndexNotReadyError:
        raise
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        error = str(exc)[:200]
    ctx.hard_fallback_elapsed = max(0.0, float(time.time() - started))
    ctx.retrieval_elapsed += ctx.hard_fallback_elapsed
    record = build_query_invocation_record(
        QueryInvocationRecordInput(
            kind="hard_fallback",
            query=ctx.query_for_retrieval,
            docs=docs,
            error=error,
            elapsed_sec=ctx.hard_fallback_elapsed,
            retriever_debug=ctx.hard_fallback_retriever_debug,
        )
    )
    ctx.retrieval_per_query.append(record.per_query_item)
    if record.error_entry:
        ctx.hard_fallback_error = error
        ctx.retrieval_errors.append(record.error_entry)
    return docs


def _merge_hard_fallback_docs(
    current: list[Document],
    incoming: list[Document],
) -> tuple[list[Document], int]:
    merged: list[Document] = []
    seen_keys: set[str] = set()
    for doc in current:
        if doc is None:
            continue
        merged.append(doc)
        key = document_key(doc)
        if key:
            seen_keys.add(key)
    added = 0
    for doc in incoming:
        if doc is None:
            continue
        key = document_key(doc)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        merged.append(doc)
        added += 1
    return merged, added


def _run_hard_fallback(ctx: RetrievalRuntimeState) -> None:
    ctx.hard_fallback_attempted = True
    if ctx.retrieval_fallback_reason is None:
        ctx.retrieval_fallback_reason = "empty_retrieval"
    fallback_docs = _invoke_hard_fallback(ctx)
    if not fallback_docs:
        return
    ctx.docs, ctx.hard_fallback_added_docs = _merge_hard_fallback_docs(
        list(ctx.docs),
        fallback_docs,
    )
    citations_after = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    citations_after, missing_count = _filter_strict_span_citations(
        citations_after,
        enabled=bool(ctx.evidence_span_strict_enabled),
    )
    ctx.evidence_span_missing_citations += missing_count
    ctx.hard_fallback_added_citations = max(0, len(citations_after) - len(ctx.citations))
    ctx.citations = citations_after
    ctx.hard_fallback_used = bool(ctx.hard_fallback_added_docs > 0 and ctx.citations)


def _run_retrieval_citations_hard_fallback_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.docs, ctx.metadata_exact_anchor_doc_order_meta = _apply_metadata_exact_anchor_doc_ordering(
        ctx.query_for_retrieval,
        [d for d in (ctx.docs) if isinstance(d, Document)],
    )
    # Attach ontology evidence after document ranking to preserve original recall candidates.
    ctx.docs.extend(ctx.state.get("ontology_docs", []))

    ctx.evidence_span_strict_enabled = bool(ctx.retrieval_contract_policy["require_evidence_spans"])
    ctx.evidence_span_missing_citations = 0

    ctx.citations = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    ctx.citations, missing_count = _filter_strict_span_citations(
        ctx.citations,
        enabled=bool(ctx.evidence_span_strict_enabled),
    )
    ctx.evidence_span_missing_citations += missing_count
    ctx.retrieval_fallback_reason: str | None = None
    if ctx.evidence_span_strict_enabled and not ctx.citations and ctx.evidence_span_missing_citations > 0:
        ctx.retrieval_fallback_reason = "strict_span_empty"

    if ctx.hard_fallback_enabled and not ctx.citations:
        _run_hard_fallback(ctx)
    return None
