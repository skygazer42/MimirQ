"""Metadata exact-anchor annotation and doc ordering for retrieval results.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``).
"""

from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retrieval.orchestration.common import _doc_key
from app.rag.retriever import _apply_metadata_exact_anchor_to_result, _float_or_default


def _metadata_exact_anchor_doc_order_meta() -> dict[str, Any]:
    return {
        "applied": False,
        "annotated": 0,
        "score_promoted": 0,
        "top_changed": False,
    }


def _apply_metadata_exact_anchor_doc_ordering(
    query: str,
    docs: list[Document],
) -> tuple[list[Document], dict[str, Any]]:
    meta = _metadata_exact_anchor_doc_order_meta()
    if not query or not docs:
        meta["reason"] = "empty"
        return docs, meta

    phrase_boost_weight = max(
        0.0,
        float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
    )
    rows: list[tuple[Document, int]] = []
    annotated = 0
    promoted = 0
    for idx, doc in enumerate(docs):
        if not isinstance(doc, Document):
            continue
        doc_meta = dict(doc.metadata or {})
        result = {"metadata": doc_meta, "score": doc_meta.get("score")}
        changed = _apply_metadata_exact_anchor_to_result(
            query=query,
            result=result,
            phrase_boost_weight=phrase_boost_weight,
            promote_score=True,
        )
        if changed:
            annotated += 1
            for key in (
                "metadata_exact_match_score",
                "metadata_exact_match_primary_score",
                "metadata_exact_match_boost",
                "metadata_exact_match_field",
                "metadata_exact_match_value",
                "metadata_exact_match_fields",
                "metadata_exact_match_values",
                "metadata_exact_match_promoted_score",
            ):
                if key in result:
                    doc_meta[key] = result.get(key)
            if "score" in result:
                old_score = _float_or_default(doc.metadata.get("score") if isinstance(doc.metadata, dict) else None, 0.0)
                new_score = _float_or_default(result.get("score"), 0.0)
                if new_score > old_score:
                    promoted += 1
                doc_meta["score"] = result.get("score")
            doc = Document(
                page_content=doc.page_content,
                metadata=doc_meta,
                id=getattr(doc, "id", None) or doc_meta.get("chunk_id"),
            )
        rows.append((doc, idx))

    if annotated <= 0:
        meta["reason"] = "no_anchor_matches"
        return [doc for doc, _idx in rows], meta

    before_top = _doc_key(rows[0][0]) if rows else ""
    best_anchor_score = max(
        _float_or_default(
            row[0].metadata.get("metadata_exact_match_score") if isinstance(row[0].metadata, dict) else None,
            0.0,
        )
        for row in rows
    )

    def _doc_order_key(row: tuple[Document, int]) -> tuple[float, float, int]:
        doc, idx = row
        doc_meta = doc.metadata if isinstance(doc.metadata, dict) else {}
        metadata_score = _float_or_default(doc_meta.get("metadata_exact_match_score"), 0.0)
        score = _float_or_default(doc_meta.get("score"), 0.0)
        if best_anchor_score >= 0.65:
            return (-metadata_score, -score, int(idx))
        return (-score, -metadata_score, int(idx))

    rows.sort(
        key=_doc_order_key
    )
    out = [doc for doc, _idx in rows]
    after_top = _doc_key(out[0]) if out else ""
    meta["applied"] = True
    meta["annotated"] = int(annotated)
    meta["score_promoted"] = int(promoted)
    meta["top_changed"] = bool(before_top and after_top and before_top != after_top)
    meta["reason"] = "applied"
    return out, meta
