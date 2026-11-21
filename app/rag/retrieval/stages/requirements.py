"""Verify mandatory sources and execute the configured second pass."""

from typing import Any

from langchain_core.documents import Document

from app.rag.policy.must_recall import (
    build_must_recall_fail_reasons,
    evaluate_required_source_keys,
)
from app.rag.policy.recall_obligation import build_must_recall_proof
from app.rag.retrieval.evidence.citations import build_citations_from_docs
from app.rag.retrieval.evidence.gaps import evaluate_evidence_anchor_expectations
from app.rag.retrieval.evidence.quality import _coverage_proxy_from_citations
from app.rag.retrieval.ranking.fusion import annotate_documents_with_role
from app.rag.retrieval.recall.retriever import hybrid_retriever
from app.rag.retrieval.results import _log_orchestrator_fallback, document_key
from app.rag.retrieval.stages.followup import _filter_strict_span_citations
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.storage.bm25.milvus import BM25IndexNotReadyError


def _must_recall_doc_keys(docs: list[Document]) -> set[str]:
    keys: set[str] = set()
    for doc in docs:
        if doc is None:
            continue
        key = document_key(doc)
        if key:
            keys.add(key)
    return keys


def _invoke_must_recall_second_pass(ctx: RetrievalRuntimeState) -> list[Document]:
    try:
        retriever_update = dict(ctx.retriever_update)
        retriever_update.update(
            {
                "retrieval_mode": ctx.must_recall_second_pass_mode,
                "k": int(ctx.must_recall_second_pass_top_k),
                "enable_reranker": False,
            }
        )
        retriever_obj = hybrid_retriever.model_copy(update=retriever_update)
        return annotate_documents_with_role(
            retriever_obj.invoke(ctx.query_for_retrieval) or [],
            "must_recall_second_pass",
        )
    except BM25IndexNotReadyError:
        raise
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.must_recall_second_pass_error = str(exc)[:200]
        return []


def _merge_must_recall_second_pass_docs(
    current: list[Document],
    incoming: list[Document],
    *,
    seen_keys: set[str],
) -> tuple[list[Document], int]:
    merged = list(current)
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


def _must_recall_evaluations(ctx: RetrievalRuntimeState) -> tuple[dict[str, Any], dict[str, Any]]:
    citations = [citation for citation in ctx.citations if isinstance(citation, dict)]
    return (
        evaluate_required_source_keys(
            citations=citations,
            required_source_keys=ctx.must_recall_expected_source_keys,
        ),
        evaluate_evidence_anchor_expectations(
            citations=citations,
            required_fields=ctx.must_recall_required_anchor_fields,
            exclude_retrieval_role_prefixes=["hierarchy_"],
        ),
    )


def _run_must_recall_second_pass(
    ctx: RetrievalRuntimeState,
    *,
    source_eval: dict[str, Any],
    anchor_eval: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ctx.must_recall_second_pass_attempted = True
    before_doc_keys = _must_recall_doc_keys(list(ctx.docs))
    citations_before = list(ctx.citations)
    fallback_docs = _invoke_must_recall_second_pass(ctx)
    if not fallback_docs:
        return source_eval, anchor_eval
    ctx.docs, ctx.must_recall_second_pass_added_docs = _merge_must_recall_second_pass_docs(
        list(ctx.docs),
        fallback_docs,
        seen_keys=before_doc_keys,
    )
    citations_after = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    ctx.citations, missing_count = _filter_strict_span_citations(
        citations_after,
        enabled=bool(ctx.evidence_span_strict_enabled),
    )
    ctx.evidence_span_missing_citations += missing_count
    ctx.must_recall_second_pass_added_citations = max(0, len(ctx.citations) - len(citations_before))
    after_source_eval, after_anchor_eval = _must_recall_evaluations(ctx)
    after_missing_sources = list(after_source_eval["missing_source_keys"])
    after_anchor_missing = int(after_anchor_eval["missing_any"])
    ctx.must_recall_second_pass_used = not after_missing_sources and after_anchor_missing <= 0
    ctx.must_recall_second_pass_diff = {
        "before_missing_source_keys": list(source_eval["missing_source_keys"]),
        "after_missing_source_keys": after_missing_sources,
        "before_anchor_missing_any": int(anchor_eval["missing_any"]),
        "after_anchor_missing_any": after_anchor_missing,
        "before_citations": len(citations_before),
        "after_citations": len(ctx.citations),
        "added_docs": ctx.must_recall_second_pass_added_docs,
        "added_citations": ctx.must_recall_second_pass_added_citations,
    }
    return after_source_eval, after_anchor_eval


def _must_recall_status(ctx: RetrievalRuntimeState) -> str:
    if not ctx.must_recall_enabled:
        return "disabled"
    if ctx.must_recall_passed and ctx.must_recall_second_pass_attempted:
        return "partial_miss_recovered"
    if ctx.must_recall_passed:
        return "passed"
    return "failed"


def _run_retrieval_must_recall_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    must_recall_source_eval, ctx.must_recall_anchor_eval = _must_recall_evaluations(ctx)
    initial_missing_source_keys = list(must_recall_source_eval["missing_source_keys"])
    initial_anchor_missing_any = int(ctx.must_recall_anchor_eval["missing_any"])
    partial_miss_detected = bool(
        ctx.must_recall_enabled and (bool(initial_missing_source_keys) or initial_anchor_missing_any > 0)
    )

    ctx.must_recall_second_pass_attempted = False
    ctx.must_recall_second_pass_used = False
    ctx.must_recall_second_pass_error: str | None = None
    ctx.must_recall_second_pass_added_docs = 0
    ctx.must_recall_second_pass_added_citations = 0
    ctx.must_recall_second_pass_diff: dict[str, Any] | None = None

    if partial_miss_detected and ctx.must_recall_second_pass_enabled:
        must_recall_source_eval, ctx.must_recall_anchor_eval = _run_must_recall_second_pass(
            ctx,
            source_eval=must_recall_source_eval,
            anchor_eval=ctx.must_recall_anchor_eval,
        )

    ctx.missing_source_keys = list(must_recall_source_eval["missing_source_keys"])
    anchor_missing_any = int(ctx.must_recall_anchor_eval["missing_any"])
    ctx.must_recall_passed = bool(
        (not ctx.must_recall_enabled) or (not ctx.missing_source_keys and anchor_missing_any <= 0)
    )
    ctx.must_recall_fail_reasons = build_must_recall_fail_reasons(
        citations_count=len(ctx.citations),
        missing_source_keys=ctx.missing_source_keys,
        anchor_missing_any=anchor_missing_any,
        second_pass_attempted=ctx.must_recall_second_pass_attempted,
        second_pass_used=ctx.must_recall_second_pass_used,
    )
    ctx.must_recall_status = _must_recall_status(ctx)
    ctx.must_recall_second_pass_payload = {
        "enabled": bool(ctx.must_recall_second_pass_enabled),
        "attempted": bool(ctx.must_recall_second_pass_attempted),
        "used": bool(ctx.must_recall_second_pass_used),
        "mode": str(ctx.must_recall_second_pass_mode),
        "top_k": int(ctx.must_recall_second_pass_top_k),
        "added_docs": int(ctx.must_recall_second_pass_added_docs),
        "added_citations": int(ctx.must_recall_second_pass_added_citations),
        "error": ctx.must_recall_second_pass_error,
        "diff": (dict(ctx.must_recall_second_pass_diff) if ctx.must_recall_second_pass_diff is not None else None),
    }
    ctx.must_recall_proof = build_must_recall_proof(
        enabled=bool(ctx.must_recall_enabled),
        status=str(ctx.must_recall_status),
        passed=bool(ctx.must_recall_passed),
        required_source_keys=ctx.must_recall_expected_source_keys,
        required_anchor_fields=ctx.must_recall_required_anchor_fields,
        source_eval=must_recall_source_eval,
        anchor_eval=ctx.must_recall_anchor_eval,
        fail_reasons=ctx.must_recall_fail_reasons,
        second_pass=ctx.must_recall_second_pass_payload,
        contract_fail_reason_taxonomy=str(ctx.retrieval_contract_policy["contract_fail_reason_taxonomy"]),
    )

    ctx.coverage = _coverage_proxy_from_citations(ctx.citations)
    return None
