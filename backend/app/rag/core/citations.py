"""
Shared citation helpers.

These utilities convert retrieved LangChain `Document` objects into the
structured citation payload returned by both streaming and non-streaming RAG
pipelines.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from langchain_core.documents import Document

from app.core.config import settings


_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}")


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _extract_query_terms(query: str, *, max_terms: int = 8) -> list[str]:
    raw = (query or "").strip()
    if not raw:
        return []
    terms: list[str] = []
    for m in _QUERY_TOKEN_RE.finditer(raw):
        t = (m.group(0) or "").strip()
        if not t:
            continue
        t_norm = t.casefold() if t.isascii() else t
        if t_norm in terms:
            continue
        terms.append(t_norm)
        if len(terms) >= max_terms:
            break
    # Prefer longer terms for matching.
    return sorted(terms, key=len, reverse=True)


def _find_first_match(text: str, terms: list[str]) -> tuple[int, str] | None:
    if not text or not terms:
        return None
    folded = text.casefold()
    best: tuple[int, str] | None = None
    for t in terms:
        if not t:
            continue
        idx = folded.find(t.casefold()) if str(t).isascii() else text.find(str(t))
        if idx < 0:
            continue
        if best is None or idx < best[0]:
            best = (idx, str(t))
    return best


def _build_snippet(text: str, query: str | None, *, max_chars: int = 220) -> tuple[str, list[str]]:
    max_chars = max(60, int(max_chars or 0))
    clean = _collapse_ws(text)
    if not clean:
        return "", []

    terms = _extract_query_terms(query or "", max_terms=10) if query else []
    hit = _find_first_match(clean, terms) if terms else None
    if hit is None:
        snippet = clean[:max_chars]
        if len(clean) > max_chars:
            snippet += "..."
        return snippet, []

    idx, _ = hit
    before = max_chars // 3
    after = max_chars - before
    start = max(0, idx - before)
    end = min(len(clean), idx + after)
    snippet = clean[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean):
        snippet = snippet + "..."

    matched: list[str] = []
    snippet_folded = snippet.casefold()
    for t in terms:
        if not t:
            continue
        if str(t).isascii():
            if t.casefold() in snippet_folded:
                matched.append(str(t))
        else:
            if str(t) in snippet:
                matched.append(str(t))
    return snippet, matched


def build_citations_from_docs(
    docs: List[Document],
    *,
    retrieval_elapsed_sec: float,
    retrieval_mode: str,
    query: str | None = None,
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
        snippet, matched_terms = _build_snippet(doc.page_content or "", query, max_chars=220)

        citation: Dict[str, Any] = {
            "chunk_id": chunk_id,
            "document_id": meta.get("document_id"),
            "document_name": meta.get("source", "Unknown"),
            "chunk_content": snippet or ((doc.page_content or "")[:200] + "..."),
            "matched_terms": matched_terms,
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

