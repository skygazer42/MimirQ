"""Sparse and ColBERT query operations over the shared corpus and artifact owners."""

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.filters import match_metadata_filter
from app.rag.retrieval.corpus_index import CorpusIndex, CorpusScope
from app.rag.retrieval.hybrid.common import _log_retriever_fallback
from app.rag.retrieval.hybrid.result_values import (
    candidate_metadata_from_doc,
    result_content_from_doc,
    top_scored_results,
)


@dataclass(frozen=True)
class CorpusChannelRequest:
    query: str
    top_k: int
    scope: CorpusScope
    metadata_filter: dict[str, Any] | None = None
    metadata_filter_enabled: bool = True


@dataclass(frozen=True)
class SparseSearchPolicy:
    enabled: bool
    provider: str


@dataclass(frozen=True)
class CorpusChannelOutcome:
    records: list[dict[str, Any]]
    status: dict[str, Any]
    failure: Exception | None = None


def sparse_provider_status(policy: SparseSearchPolicy) -> dict[str, Any]:
    from app.rag.retrieval.sparse import resolve_sparse_provider_capability

    return resolve_sparse_provider_capability(
        requested_provider=policy.provider, sparse_enabled=policy.enabled, default_provider="deterministic"
    )


def skipped_sparse_status(policy: SparseSearchPolicy) -> dict[str, Any]:
    return {**sparse_provider_status(policy), "outcome": "skipped", "candidates": 0}


def _allowed(document: Document, request: CorpusChannelRequest, allowed_document_ids: set[str]) -> bool:
    if allowed_document_ids and str(document.metadata.get("document_id")) not in allowed_document_ids:
        return False
    return not (
        request.metadata_filter_enabled
        and request.metadata_filter
        and not match_metadata_filter(document.metadata, request.metadata_filter)
    )


def _sparse_results(
    scored: list[tuple[str, float]], docs: tuple[Document, ...], request: CorpusChannelRequest
) -> list[dict[str, Any]]:
    by_id = {str(document.id): document for document in docs if document.id is not None}
    allowed_document_ids = {str(value) for value in request.scope.document_ids}
    records = []
    for doc_id, score in scored:
        document = by_id.get(str(doc_id))
        if document is None or not _allowed(document, request, allowed_document_ids):
            continue
        metadata = candidate_metadata_from_doc(document.metadata, chunk_id=document.id)
        metadata["sparse_score"] = float(score)
        records.append(
            {
                "chunk_id": document.id,
                "content": result_content_from_doc(document),
                "metadata": metadata,
                "score": float(score),
            }
        )
    return top_scored_results(records, request.top_k)


def search_sparse(
    request: CorpusChannelRequest, *, corpus_index: CorpusIndex, policy: SparseSearchPolicy
) -> CorpusChannelOutcome:
    raw_query = request.query.strip()
    if not raw_query or not policy.enabled:
        return CorpusChannelOutcome(records=[], status=skipped_sparse_status(policy))
    snapshot = corpus_index.load_corpus_snapshot(request.scope)
    status = sparse_provider_status(policy)
    provider = str(status.get("effective_provider") or "deterministic").strip().lower() or "deterministic"
    reason = str(status.get("reason") or "none")
    outcome = "error"
    records = []
    failure = None
    started = time.perf_counter()
    from app.rag.retrieval.sparse_prometheus_metrics import observe_sparse_index_load, observe_sparse_search

    try:
        if not snapshot.documents:
            outcome, reason = "skipped", "scope_empty"
        else:
            from app.rag.retrieval.sparse import (
                SparseIndexStore,
                build_sparse_provider_config,
                get_sparse_encoder,
                parse_synonyms,
                topk_scores,
            )

            artifacts = corpus_index.artifacts.sparse
            synonyms_raw, synonyms, provider_config = artifacts._sparse_runtime_inputs(
                provider=provider,
                build_sparse_provider_config=build_sparse_provider_config,
                parse_synonyms=parse_synonyms,
            )
            vectors, load_error, build_error = artifacts._ensure_sparse_vectors_for_search(
                cache_key=snapshot.cache_key,
                provider=provider,
                provider_config=provider_config,
                docs=list(snapshot.documents),
                version_token=corpus_index.resolve_version(request.scope),
                store_cls=SparseIndexStore,
                observe_sparse_index_load=observe_sparse_index_load,
            )
            if build_error is not None and len(vectors) != len(snapshot.documents):
                failure, reason = build_error, "index_build_failed"
            else:
                if reason == "none" and load_error:
                    reason = "index_load_error"
                encoder = get_sparse_encoder(provider=provider, synonyms=synonyms, synonyms_raw=synonyms_raw)
                scored = topk_scores(
                    query_vec=encoder.encode_batch([raw_query])[0], docs=vectors, k=max(0, request.top_k)
                )
                records = _sparse_results(scored, snapshot.documents, request)
                outcome = "ok" if records else "empty"
                if not records and reason == "none":
                    reason = "no_candidates"
    except Exception as exc:
        _log_retriever_fallback("_search_sparse", exc)
        failure = exc
        if reason == "none":
            reason = "exception"
    finally:
        observe_sparse_search(
            provider=provider,
            outcome=outcome,
            duration_sec=time.perf_counter() - started,
            candidates_count=len(records),
            reason=reason,
        )
    return CorpusChannelOutcome(
        records=records,
        status={
            **status,
            "effective_provider": provider,
            "status": str(status.get("status") or "ready"),
            "outcome": outcome,
            "reason": reason,
            "candidates": len(records),
        },
        failure=failure,
    )


def _colbert_results(
    scored: list[tuple[int, float]], doc_ids: list[str], docs: tuple[Document, ...], request: CorpusChannelRequest
) -> list[dict[str, Any]]:
    by_id = {str(document.id): document for document in docs if document.id is not None}
    allowed_document_ids = {str(value) for value in request.scope.document_ids}
    records = []
    for index, score in scored:
        if index < 0 or index >= len(doc_ids):
            continue
        doc_id = str(doc_ids[int(index)])
        document = by_id.get(doc_id)
        if document is None or not _allowed(document, request, allowed_document_ids):
            continue
        metadata = dict(document.metadata)
        metadata.setdefault("chunk_id", doc_id)
        metadata["colbert_score"] = float(score)
        records.append(
            {
                "chunk_id": doc_id,
                "content": result_content_from_doc(document),
                "metadata": metadata,
                "score": float(score),
            }
        )
    return records


def search_colbert(request: CorpusChannelRequest, *, corpus_index: CorpusIndex) -> CorpusChannelOutcome:
    raw_query = request.query.strip()
    if not raw_query or not settings.COLBERT_RETRIEVAL_ENABLED:
        return CorpusChannelOutcome(records=[], status={})
    snapshot = corpus_index.load_corpus_snapshot(request.scope)
    if not snapshot.documents:
        return CorpusChannelOutcome(records=[], status={})
    from app.rag.retrieval.colbert_ann import (
        ColbertAnnIndexStore,
        build_colbert_provider_config,
        get_dense_embedder,
        resolve_colbert_retrieval_capability,
        topk_cosine_scores,
    )

    artifacts = corpus_index.artifacts.colbert
    max_docs = artifacts._resolve_colbert_max_docs()
    readiness = resolve_colbert_retrieval_capability(
        colbert_enabled=settings.COLBERT_RETRIEVAL_ENABLED,
        requested_provider=artifacts._colbert_provider_name(),
        docs_count=len(snapshot.documents),
        max_docs=max_docs,
    )
    status = {"readiness": readiness}
    if readiness.get("reason") == "too_many_docs":
        artifacts.clear_scope(snapshot.cache_key)
        return CorpusChannelOutcome(
            records=[],
            status={
                **status,
                "skipped_reason": "too_many_docs",
                "docs_n": len(snapshot.documents),
                "max_docs": max_docs,
            },
        )
    if not readiness.get("ready", False):
        return CorpusChannelOutcome(records=[], status={**status, "skipped_reason": "provider_unready"})
    provider = str(readiness.get("effective_provider") or "deterministic").strip().lower() or "deterministic"
    try:
        index = artifacts._ensure_colbert_search_index(
            cache_key=snapshot.cache_key,
            docs=list(snapshot.documents),
            provider_config=artifacts._build_colbert_provider_config(build_colbert_provider_config, provider=provider),
            expected_fp=artifacts._colbert_corpus_fingerprint(list(snapshot.documents)),
            store_cls=ColbertAnnIndexStore,
        )
        if index is None:
            raise RuntimeError("ColBERT index did not become ready")
        embedder = get_dense_embedder(provider=provider, deterministic_dim=settings.COLBERT_RETRIEVAL_EMBED_DIM)
        query_vector = embedder.encode_batch([raw_query])[0]
        scored = topk_cosine_scores(query_vec=query_vector, doc_vecs=index.vectors, k=max(0, request.top_k))
        return CorpusChannelOutcome(
            records=_colbert_results(scored, index.doc_ids, snapshot.documents, request), status=status
        )
    except Exception as exc:
        _log_retriever_fallback("_search_colbert_dense", exc)
        return CorpusChannelOutcome(records=[], status=status, failure=exc)
