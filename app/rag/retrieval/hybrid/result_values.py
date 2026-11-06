"""Shared result projections and stable ordering for corpus and hybrid channels."""

import heapq
from typing import Any

from langchain_core.documents import Document

from app.rag.core.hashing import stable_hash
from app.rag.retrieval.hybrid.common import (
    _PIPELINE_PLUGIN_METADATA_KEYS,
    _PLATFORM_METADATA_VIEW_KEYS,
    _RETRIEVAL_DISPLAY_CONTENT_KEY,
    _float_or_default,
)


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
        "chunk_id": meta.get("chunk_id") or chunk_id,
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
    meta = doc.metadata or {}
    preserved = meta.get(_RETRIEVAL_DISPLAY_CONTENT_KEY)
    if isinstance(preserved, str) and preserved:
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
    content = str(result.get("content") or "")
    return f"content:{stable_hash(content)}"


def top_scored_results(results: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    if not results:
        return []
    return heapq.nsmallest(
        max(0, int(top_k or 0)),
        results,
        key=lambda item: (-_float_or_default(item.get("score"), 0.0), result_key(item)),
    )
