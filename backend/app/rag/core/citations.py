"""
Shared citation helpers.

These utilities convert retrieved LangChain `Document` objects into the
structured citation payload returned by both streaming and non-streaming RAG
pipelines.
"""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.documents import Document

from app.core.config import settings


def build_citations_from_docs(
    docs: List[Document],
    *,
    retrieval_elapsed_sec: float,
    retrieval_mode: str,
) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []
    for doc in docs:
        meta = doc.metadata or {}

        v_score_raw = float(meta.get("vector_score", 0.0) or 0.0)
        b_score_raw = float(meta.get("bm25_score", 0.0) or 0.0)
        rerank_score = meta.get("rerank_score")
        retrieval_score = meta.get("retrieval_score")

        if retrieval_mode == "mmr":
            hit_type = "mmr"
        elif v_score_raw > b_score_raw:
            hit_type = "vector"
        elif b_score_raw > v_score_raw:
            hit_type = "keyword"
        else:
            hit_type = "hybrid"

        img_id = meta.get("img_id")
        img_url = f"/api/v1/documents/image-url/{img_id}" if img_id else None

        chunk_id = getattr(doc, "id", None) or meta.get("chunk_id")

        citation: Dict[str, Any] = {
            "chunk_id": chunk_id,
            "document_id": meta.get("document_id"),
            "document_name": meta.get("source", "Unknown"),
            "chunk_content": (doc.page_content or "")[:200] + "...",
            "page_number": meta.get("page"),
            "relevance_score": round(float(meta.get("score", 0.0) or 0.0), 2),
            "vector_score": round(v_score_raw, 3),
            "bm25_score": round(b_score_raw, 3),
            "keyword_score": round(float(meta.get("keyword_score", 0.0) or 0.0), 3),
            "rerank_score": round(float(rerank_score), 3) if rerank_score is not None else None,
            "retrieval_score": round(float(retrieval_score), 3) if retrieval_score is not None else None,
            "reranker_provider": meta.get("reranker_provider"),
            "rerank_elapsed_sec": meta.get("rerank_elapsed_sec"),
            "rerank_model_used": meta.get("rerank_model_used"),
            "retrieval_mode": retrieval_mode,
            "vector_backend": settings.VECTOR_BACKEND,
            "retrieval_elapsed_sec": round(float(retrieval_elapsed_sec or 0.0), 3),
            "hit_type": hit_type,
        }

        if img_id:
            citation["img_id"] = img_id
            citation["img_url"] = img_url
            citation["has_image"] = True
        else:
            citation["has_image"] = False

        citations.append(citation)
    return citations

