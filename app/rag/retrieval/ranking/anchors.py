"""Annotate and order evidence documents by their root metadata anchors."""

from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.retrieval.ranking.metadata import match_metadata_anchors, normalize_exact_anchor
from app.rag.retrieval.results import document_key


def _iter_metadata_exact_anchor_values(meta: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(field: str, value: Any) -> None:
        values: list[Any]
        if isinstance(value, (list, tuple)):
            values = list(value)
        else:
            values = [value]
        for item in values:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if not text:
                continue
            key = (field, text)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)

    for field, value in meta.items():
        field_s = field.strip()
        if not field_s or field_s.startswith("_"):
            continue
        add(field_s, value)

    return out


def _metadata_exact_anchor_match(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    query_norm = normalize_exact_anchor(query, compact=True)
    if not query_norm:
        return {}
    return match_metadata_anchors(
        query_norm, _iter_metadata_exact_anchor_values(meta), normalize=normalize_exact_anchor
    )


def _float_or_default(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (OverflowError, TypeError, ValueError):
        return float(default)


def _apply_metadata_exact_anchor_to_result(
    *,
    query: str,
    result: dict[str, Any],
    phrase_boost_weight: float,
    promote_score: bool = False,
) -> bool:
    meta_for_anchor = dict(result.get("metadata") or {})
    metadata_match = _metadata_exact_anchor_match(query, meta_for_anchor)
    if not metadata_match:
        return False

    match_score = metadata_match["score"]
    metadata_boost = match_score * max(0.0, float(phrase_boost_weight or 0.0))
    result["metadata_exact_match_score"] = match_score
    result["metadata_exact_match_primary_score"] = metadata_match["primary_score"]
    result["metadata_exact_match_boost"] = metadata_boost
    result["metadata_exact_match_field"] = metadata_match["field"]
    result["metadata_exact_match_value"] = metadata_match["value"]
    result["metadata_exact_match_fields"] = list(metadata_match["fields"])
    result["metadata_exact_match_values"] = list(metadata_match["values"])

    if promote_score:
        current_score = _float_or_default(result.get("score"), 0.0)
        promoted_score = max(current_score, match_score)
        if promoted_score > current_score:
            result["score"] = round(promoted_score, 6)
            result["metadata_exact_match_promoted_score"] = round(promoted_score, 6)
    return True


def _metadata_exact_anchor_doc_order_meta() -> dict[str, Any]:
    return {
        "applied": False,
        "annotated": 0,
        "score_promoted": 0,
        "top_changed": False,
    }


def _annotate_anchor_docs(
    *,
    query: str,
    docs: list[Document],
    phrase_boost_weight: float,
) -> tuple[list[tuple[Document, int]], int, int]:
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
                old_score = _float_or_default(doc_meta.get("score"), 0.0)
                new_score = _float_or_default(result.get("score"), 0.0)
                if new_score > old_score:
                    promoted += 1
                doc_meta["score"] = result.get("score")
            doc = Document(
                page_content=doc.page_content,
                metadata=doc_meta,
                id=doc.id or doc_meta.get("chunk_id"),
            )
        rows.append((doc, idx))
    return rows, annotated, promoted


def _metadata_exact_anchor_sort_key(
    row: tuple[Document, int],
    *,
    best_anchor_score: float,
) -> tuple[float, float, int]:
    doc, idx = row
    doc_meta = doc.metadata
    metadata_score = _float_or_default(doc_meta.get("metadata_exact_match_score"), 0.0)
    score = _float_or_default(doc_meta.get("score"), 0.0)
    if best_anchor_score >= 0.65:
        return (-metadata_score, -score, idx)
    return (-score, -metadata_score, idx)


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
        settings.RETRIEVAL_EXACT_PHRASE_RERANK_BOOST,
    )
    rows, annotated, promoted = _annotate_anchor_docs(
        query=query,
        docs=docs,
        phrase_boost_weight=phrase_boost_weight,
    )
    if annotated <= 0:
        meta["reason"] = "no_anchor_matches"
        return [doc for doc, _idx in rows], meta

    before_top = document_key(rows[0][0]) if rows else ""
    best_anchor_score = max(
        _float_or_default(
            row[0].metadata.get("metadata_exact_match_score"),
            0.0,
        )
        for row in rows
    )
    rows.sort(key=lambda row: _metadata_exact_anchor_sort_key(row, best_anchor_score=best_anchor_score))
    out = [doc for doc, _idx in rows]
    after_top = document_key(out[0]) if out else ""
    meta["applied"] = True
    meta["annotated"] = annotated
    meta["score_promoted"] = promoted
    meta["top_changed"] = bool(before_top and after_top and before_top != after_top)
    meta["reason"] = "applied"
    return out, meta
