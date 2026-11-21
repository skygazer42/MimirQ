"""Candidate projections, stable ordering, and channel result preparation."""

import heapq
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.hashing import stable_hash
from app.rag.retrieval.recall.common import (
    _PIPELINE_PLUGIN_METADATA_KEYS,
    _PLATFORM_METADATA_VIEW_KEYS,
    _RETRIEVAL_DISPLAY_CONTENT_KEY,
    _apply_metadata_exact_anchor_to_result,
    _float_or_default,
)


@dataclass(frozen=True)
class HybridChannelResults:
    vector_results: list[dict[str, Any]]
    bm25_results: list[dict[str, Any]]
    lexical_results: list[dict[str, Any]]
    metadata_exact_pre_fusion_stats: dict[str, Any]


def candidate_metadata_from_doc(meta: dict[str, Any], *, chunk_id: Any = None) -> dict[str, Any]:
    pipeline_meta = meta.get("pipeline") if isinstance(meta.get("pipeline"), dict) else {}
    out = {
        "tenant_id": meta.get("tenant_id"),
        "dataset_id": meta.get("dataset_id"),
        "document_id": meta.get("document_id"),
        "source": meta.get("source", "unknown"),
        "page": meta.get("page"),
        "page_number": meta.get("page_number"),
        "chunk_index": meta.get("chunk_index"),
        "chunk_id": (meta.get("chunk_id", chunk_id)),
        "img_id": meta.get("img_id"),
        "image_id": meta.get("image_id"),
        "image_url": meta.get("image_url"),
    }
    for key in _PIPELINE_PLUGIN_METADATA_KEYS:
        value = meta.get(key) or pipeline_meta.get(key)
        if value:
            out[key] = value
    for key in ("doc_pipeline_key", "pipeline_hash", "active_pipeline_hash"):
        value = meta.get(key) or pipeline_meta.get(key)
        if value:
            out[key] = value
    for key in _PLATFORM_METADATA_VIEW_KEYS:
        value = meta.get(key)
        if isinstance(value, dict) and value:
            out[key] = value
    return out


def result_content_from_doc(doc: Document) -> str:
    meta = doc.metadata
    preserved = meta.get(_RETRIEVAL_DISPLAY_CONTENT_KEY)
    if isinstance(preserved, str):
        return preserved
    return doc.page_content


def result_key(result: dict[str, Any]) -> str:
    meta = result.get("metadata") or {}
    doc_id = meta.get("document_id")
    chunk_index = meta.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        return f"{doc_id}:{chunk_index}"
    cid = result.get("chunk_id") or meta.get("chunk_id")
    if cid:
        return str(cid)
    content = result["content"]
    return f"content:{stable_hash(content)}"


def top_scored_results(results: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    return heapq.nsmallest(
        max(0, top_k),
        results,
        key=lambda item: (-_float_or_default(item.get("score"), 0.0), result_key(item)),
    )


def _filter_vector_results_by_document_ids(
    results: list[dict[str, Any]],
    *,
    document_ids: list[Any] | None,
) -> list[dict[str, Any]]:
    if not results or not document_ids:
        return results

    allowed_document_ids = {str(document_id) for document_id in document_ids if document_id is not None}
    if not allowed_document_ids:
        return results

    filtered_results: list[dict[str, Any]] = []
    for result in results:
        metadata = result.get("metadata") or {}
        document_id = metadata.get("document_id") or result.get("document_id")
        if document_id is None:
            continue
        if str(document_id) in allowed_document_ids:
            filtered_results.append(result)
    return filtered_results


def _apply_vector_client_filter(
    results: list[dict[str, Any]],
    *,
    vector_filter: dict[str, Any] | None,
    runtime_shards_present: bool,
    match_metadata_filter: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    vector_client_filter = dict((vector_filter if vector_filter is not None else {}))
    if runtime_shards_present:
        vector_client_filter.pop("embedding_space_hash", None)
    if not vector_client_filter:
        return results
    return [result for result in results if match_metadata_filter((result.get("metadata") or {}), vector_client_filter)]


def _backfill_chunk_ids(
    results: list[dict[str, Any]],
    *,
    chunk_id_lookup: Mapping[str, str] | None,
) -> None:
    lookup = chunk_id_lookup if chunk_id_lookup is not None else {}
    for result in results:
        metadata = result.get("metadata") or {}
        existing_chunk_id = result.get("chunk_id") or metadata.get("chunk_id")
        if existing_chunk_id:
            chunk_id = str(existing_chunk_id)
            result["chunk_id"] = chunk_id
            metadata = dict(metadata)
            metadata["chunk_id"] = chunk_id
            result["metadata"] = metadata
            continue

        document_id = metadata.get("document_id")
        chunk_index = metadata.get("chunk_index")
        if document_id is None or chunk_index is None:
            continue

        chunk_id = None
        document_pipeline_key = metadata.get("doc_pipeline_key")
        if document_pipeline_key is not None:
            chunk_id = lookup.get(f"{document_pipeline_key}:{chunk_index}")
        if not chunk_id:
            chunk_id = lookup.get(f"{document_id}:{chunk_index}")
        if not chunk_id:
            continue

        result["chunk_id"] = chunk_id
        metadata["chunk_id"] = chunk_id
        result["metadata"] = metadata


def normalize_vector_channel_results(
    results: list[dict[str, Any]],
    *,
    document_ids: list[Any] | None,
    vector_filter: dict[str, Any] | None,
    runtime_shards_present: bool,
    chunk_id_lookup: Mapping[str, str] | None,
    match_metadata_filter: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    """Apply client-side vector scope checks and chunk-id backfill."""
    normalized = _filter_vector_results_by_document_ids(results, document_ids=document_ids)

    normalized = _apply_vector_client_filter(
        normalized,
        vector_filter=vector_filter,
        runtime_shards_present=runtime_shards_present,
        match_metadata_filter=match_metadata_filter,
    )

    _backfill_chunk_ids(normalized, chunk_id_lookup=chunk_id_lookup)

    return normalized


def prepare_hybrid_channel_results(
    *,
    query: str,
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    lexical_results: list[dict[str, Any]],
    document_ids: list[Any] | None,
    vector_filter: dict[str, Any] | None,
    runtime_shards_present: bool,
    chunk_id_lookup: Mapping[str, str] | None,
    match_metadata_filter: Callable[[dict[str, Any], dict[str, Any]], bool],
    metadata_exact_pre_fusion_enabled: bool,
    phrase_boost_weight: float,
) -> HybridChannelResults:
    normalized_vector_results = normalize_vector_channel_results(
        vector_results,
        document_ids=document_ids,
        vector_filter=vector_filter,
        runtime_shards_present=runtime_shards_present,
        chunk_id_lookup=chunk_id_lookup,
        match_metadata_filter=match_metadata_filter,
    )

    metadata_exact_pre_fusion_stats: dict[str, Any] = {
        "enabled": bool(metadata_exact_pre_fusion_enabled),
        "annotated": 0,
        "promoted": 0,
    }
    if metadata_exact_pre_fusion_enabled and query:
        for channel_name, channel_items in (
            ("vector", normalized_vector_results),
            ("bm25", bm25_results),
            ("lexical", lexical_results),
        ):
            channel_annotated = 0
            channel_promoted = 0
            for item in channel_items:
                before = _float_or_default(item.get("score"), 0.0)
                if _apply_metadata_exact_anchor_to_result(
                    query=query,
                    result=item,
                    phrase_boost_weight=phrase_boost_weight,
                    promote_score=True,
                ):
                    channel_annotated += 1
                    after = _float_or_default(item.get("score"), 0.0)
                    if after > before:
                        channel_promoted += 1
            if channel_annotated:
                metadata_exact_pre_fusion_stats[channel_name] = {
                    "annotated": channel_annotated,
                    "promoted": channel_promoted,
                }
                metadata_exact_pre_fusion_stats["annotated"] += channel_annotated
                metadata_exact_pre_fusion_stats["promoted"] += channel_promoted

    return HybridChannelResults(
        vector_results=normalized_vector_results,
        bm25_results=bm25_results,
        lexical_results=lexical_results,
        metadata_exact_pre_fusion_stats=metadata_exact_pre_fusion_stats,
    )
