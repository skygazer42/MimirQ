"""Dify tracing operations."""

import uuid
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.api.schemas.dify import DifyExternalKnowledgeRecord, DifyExternalKnowledgeRequest
from app.services.dify_integration import common
from app.services.dify_integration.common import (
    _DIFY_TRACE_CITATION_METADATA_KEYS as _DIFY_TRACE_CITATION_METADATA_KEYS,
)
from app.services.metrics_logger import log_metrics

_DIFY_TRACE_QUERY_PREVIEW_MAX_CHARS = 160

_DIFY_TRACE_QUERY_PATH_MAX_CHARS = 120

_DIFY_TRACE_QUERY_PREVIEW_MAX_CHARS = 160

_DIFY_TRACE_QUERY_PATH_MAX_CHARS = 120


def _dify_trace_citation(record: DifyExternalKnowledgeRecord, *, elapsed_sec: float | None) -> dict[str, Any]:
    metadata = record.metadata
    citation = {key: metadata.get(key) for key in _DIFY_TRACE_CITATION_METADATA_KEYS if metadata.get(key) is not None}
    citation.setdefault("relevance_score", common._clamp_score(record.score))
    citation.setdefault("retrieval_score", common._clamp_score(record.score))
    citation.setdefault("retrieval_mode", "dify_external_knowledge")
    if elapsed_sec is not None:
        citation.setdefault("retrieval_elapsed_sec", elapsed_sec)
    return citation


def _first_reranker_provider(records: list[DifyExternalKnowledgeRecord]) -> str | None:
    for record in records:
        metadata = record.metadata
        provider = common._first_nonempty_str(metadata.get("reranker_provider"))
        if provider:
            return provider
    return None


def _has_dify_rerank(records: list[DifyExternalKnowledgeRecord]) -> bool:
    for record in records:
        metadata = record.metadata
        if any(
            metadata.get(key) is not None
            for key in ("reranker_provider", "rerank_score", "rerank_elapsed_sec", "rerank_model_used")
        ):
            return True
    return False


def _bounded_trace_query_preview(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:_DIFY_TRACE_QUERY_PREVIEW_MAX_CHARS]


def _dify_trace_retrieval_queries(
    *,
    question: str,
    retrieval_path: str,
    retrieval_queries: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    rows = list(retrieval_queries or [])
    if not rows:
        rows = [{"kind": "main", "query": question, "path": retrieval_path, "ok": True}]

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        query_text = str(row.get("query") or "").strip()
        query_preview = _bounded_trace_query_preview(query_text)
        path = str(row.get("path") or "").strip()[:_DIFY_TRACE_QUERY_PATH_MAX_CHARS]
        item = {
            "kind": common._first_nonempty_str(row.get("kind")) or "subq",
            "query_chars": len(query_text),
            "ok": bool(row.get("ok", True)),
        }
        if query_preview:
            item["query_preview"] = query_preview
        if path:
            item["path"] = path
        elapsed_sec = row.get("elapsed_sec")
        if isinstance(elapsed_sec, int | float):
            item["elapsed_sec"] = round(max(0.0, float(elapsed_sec)), 6)
        out.append(item)
    return out


def _log_dify_external_rag_trace(
    *,
    tenant_id: UUID,
    conversation_id: UUID | None,
    request_id: str | None,
    question: str,
    response_records: list[DifyExternalKnowledgeRecord],
    top_k: int,
    candidate_top_k: int,
    retrieval_path: str,
    elapsed_ms: float,
    metadata_anchor_fallback_count: int,
    mixed_intent_query_count: int,
    retrieval_queries: list[dict[str, Any]] | None = None,
    dify_message_id: str | None = None,
    dify_workflow_run_id: str | None = None,
) -> None:
    if conversation_id is None:
        return
    resolved_request_id = common._first_nonempty_str(request_id) or f"dify-{uuid.uuid4().hex}"
    elapsed_sec = round(max(0.0, float(elapsed_ms or 0.0)) / 1000.0, 6)
    records = list(response_records)
    citations = [_dify_trace_citation(record, elapsed_sec=elapsed_sec) for record in records]
    reranker_provider = _first_reranker_provider(records)
    per_query = _dify_trace_retrieval_queries(
        question=question,
        retrieval_path=retrieval_path,
        retrieval_queries=retrieval_queries,
    )
    log_metrics(
        {
            "event": "rag_trace",
            "source": "dify_external_knowledge",
            "conversation_id": str(conversation_id),
            "tenant_id": str(tenant_id),
            "request_id": str(resolved_request_id),
            "question": str(question or ""),
            "query_for_retrieval": str(question or ""),
            "citations_count": len(citations),
            "citations": citations,
            "retrieval": {
                "mode": "dify_external_knowledge",
                "requested_mode": "external_knowledge",
                "top_k": int(top_k),
                "query_count": max(len(per_query), 1 + max(0, int(mixed_intent_query_count or 0))),
                "per_query": per_query,
                "elapsed_sec": elapsed_sec,
                "errors": [],
                "enable_reranker": _has_dify_rerank(records),
                "reranker_provider": reranker_provider,
                "reranker_top_n": int(candidate_top_k),
            },
            "route": "dify_external_knowledge",
            "retrieval_path": str(retrieval_path or ""),
            "metadata_anchor_fallback_count": int(metadata_anchor_fallback_count or 0),
            "dify_message_id": common._first_nonempty_str(dify_message_id),
            "dify_workflow_run_id": common._first_nonempty_str(dify_workflow_run_id),
        }
    )


def _dify_trace_request_id(
    request_headers: Mapping[str, str], body: DifyExternalKnowledgeRequest, *, request_id: str | None = None
) -> str | None:
    return common._first_nonempty_str(
        body.request_id,
        common._header_value(request_headers, "x-mimirq-request-id"),
        common._header_value(request_headers, "x-request-id"),
        request_id,
    )
