"""
Chat <-> image embedding index bridge (CLIP).

Wave19-T063: Multi-modal query routing (text vs image vs table).

This module provides a small utility to inject image-chunk context docs into the
chat retrieval pipeline so:
- the LLM can read OCR/caption text,
- the UI can render safe thumbnails via img_url citations.

Notes:
- Best-effort only: should never block chat/retrieval if image deps are missing.
- Deterministic-ish: retrieval is embedding-based and bounded; no LLM calls.
"""


from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings


def convert_image_citations_to_docs(citations: list[dict[str, Any]]) -> list[Any]:
    """
    Convert `build_image_citations()` outputs into langchain Documents for injection.

    Return type is `list[Any]` to avoid importing langchain at module import time.
    """
    if not isinstance(citations, list) or not citations:
        return []

    try:
        from langchain_core.documents import Document  # type: ignore
    except Exception:
        return []

    out: list[Any] = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        chunk_id = str(c.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        doc_id = str(c.get("document_id") or "").strip() or None
        doc_name = str(c.get("document_name") or "").strip() or (doc_id or "image")
        page_content = str(c.get("chunk_content") or "").strip() or "image"

        meta: dict[str, Any] = {
            "document_id": doc_id,
            "source": doc_name,
            "chunk_id": chunk_id,
            "chunk_index": c.get("chunk_index"),
            "page": c.get("page_number"),
            "page_number": c.get("page_number"),
            "retrieval_role": "image",
            "doc_type_kwd": "image",
            # Keep score fields for UI/debugging.
            "score": c.get("relevance_score") if c.get("relevance_score") is not None else c.get("score"),
            "retrieval_score": c.get("relevance_score") if c.get("relevance_score") is not None else c.get("score"),
            # Image refs (best-effort).
            "img_id": c.get("img_id") or None,
            "img_url": c.get("img_url") or c.get("image_url") or None,
            "image_id": c.get("image_id") or None,
        }

        out.append(Document(page_content=page_content, metadata=meta, id=chunk_id))
        if len(out) >= 12:
            break

    return out


def build_chat_image_context_docs(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str | None,
    dataset_id: UUID,
    question: str,
    top_k: int = 6,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Build bounded context docs from the CLIP image embedding index for a question.

    Returns: (docs, meta)
    """
    enabled = bool(getattr(settings, "IMAGE_EMBEDDING_ENABLED", False))
    meta: dict[str, Any] = {"enabled": bool(enabled), "used": False, "reason": "not_run"}
    if not enabled:
        meta["reason"] = "IMAGE_EMBEDDING_ENABLED=false"
        return [], meta
    if db is None or tenant_id is None or dataset_id is None:
        meta["reason"] = "missing_db_or_scope"
        return [], meta

    q = str(question or "").strip()
    if not q:
        meta["reason"] = "empty_query"
        return [], meta

    try:
        from app.services.dataset_service import DatasetService  # noqa: WPS433

        DatasetService.ensure_member(db, tenant_id, str(account_id or ""))
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, ds, str(account_id or ""))
    except Exception as exc:  # noqa: BLE001
        meta["reason"] = f"dataset_not_readable:{str(exc)[:120]}"
        return [], meta

    try:
        from app.services.image_embedding_index import (  # noqa: WPS433
            build_image_citations,
            search_clip_images,
        )

        hits = search_clip_images(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            query=q,
            top_k=int(top_k or 0),
        )
        citations = build_image_citations(
            db=db,
            tenant_id=tenant_id,
            account_id=str(account_id) if str(account_id or "").strip() else None,
            dataset_id=dataset_id,
            hits=hits,
            max_items=int(top_k or 0),
        )
        docs = convert_image_citations_to_docs(citations)
        meta.update(
            {
                "reason": "ok",
                "used": bool(docs),
                "hits": int(len(hits or [])),
                "returned": int(len(docs or [])),
            }
        )
        return docs, meta
    except Exception as exc:  # noqa: BLE001
        meta["reason"] = f"image_exception:{str(exc)[:160]}"
        return [], meta


__all__ = ["build_chat_image_context_docs", "convert_image_citations_to_docs"]
