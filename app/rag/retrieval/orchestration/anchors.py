"""Metadata exact-anchor annotation and doc ordering for retrieval results.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``).
"""

import re
import unicodedata
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retrieval.orchestration.common import _doc_key

_METADATA_EXACT_ANCHOR_SKIP_FIELD_PARTS = (
    "id",
    "uuid",
    "hash",
    "path",
    "file",
    "url",
    "pipeline",
    "strategy",
    "plugin",
    "index",
    "keyword",
    "keywords",
)
_METADATA_EXACT_ANCHOR_SKIP_FIELD_PREFIXES = (
    "metadata_exact_match",
    "exact_phrase",
    "rerank",
)
_HEXISH_VALUE_RE = re.compile(r"^[a-f0-9]{12,}$", flags=re.IGNORECASE)
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_SPACE_RE = re.compile(r"\s+")
_FIELD_PART_RE = re.compile(r"[^a-z0-9]+")
_COMPACT_ANCHOR_DROP_RE = re.compile(r"[\s\"'“”‘’`´＂＇《》〈〉【】\[\]（）(){}]+")


def _normalize_exact_anchor(value: Any, *, compact: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _SPACE_RE.sub(" ", text.casefold()).strip()
    return _COMPACT_ANCHOR_DROP_RE.sub("", text) if compact else text


def _iter_metadata_exact_anchor_values(meta: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(field: str, value: Any) -> None:
        field_s = str(field or "").strip()
        if not field_s:
            return
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
            key = (field_s, text)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)

    for field, value in meta.items():
        field_s = str(field or "").strip()
        if not field_s or field_s.startswith("_"):
            continue
        add(field_s, value)

    return out


def _looks_like_metadata_exact_anchor(field: str, text: str) -> bool:
    field_norm = str(field or "").strip().lower()
    if any(field_norm.startswith(prefix) for prefix in _METADATA_EXACT_ANCHOR_SKIP_FIELD_PREFIXES):
        return False
    field_parts = {p for p in _FIELD_PART_RE.split(field_norm) if p}
    if field_parts.intersection(_METADATA_EXACT_ANCHOR_SKIP_FIELD_PARTS):
        return False
    if field_norm.endswith(("_id", "_ids", "-id", ".id")):
        return False

    normalized = _normalize_exact_anchor(text)
    if len(normalized) < 4 or len(normalized) > 160:
        return False
    if "://" in normalized or "/" in normalized or "\\" in normalized:
        return False
    if _HEXISH_VALUE_RE.fullmatch(normalized.replace("-", "")):
        return False
    if normalized.isdigit():
        return False

    cjk_count = len(_CJK_CHAR_RE.findall(normalized))
    if cjk_count:
        return cjk_count >= 4
    if "_" in normalized and " " not in normalized:
        return False
    return len(normalized) >= 8


def _metadata_exact_anchor_match(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    query_norm = _normalize_exact_anchor(query, compact=True)
    if not query_norm:
        return {}

    matches: list[dict[str, Any]] = []
    for field, anchor_text in _iter_metadata_exact_anchor_values(meta):
        if not _looks_like_metadata_exact_anchor(field, anchor_text):
            continue
        anchor_norm = _normalize_exact_anchor(anchor_text, compact=True)
        if not anchor_norm or anchor_norm not in query_norm:
            continue
        score = min(1.0, max(0.45, float(len(anchor_norm)) / float(max(1, len(query_norm)))))
        matches.append(
            {
                "field": str(field),
                "value": str(anchor_text),
                "score": round(float(score), 6),
                "norm": anchor_norm,
            }
        )

    if not matches:
        return {}

    filtered: list[dict[str, Any]] = []
    seen_norms: set[str] = set()
    for item in sorted(matches, key=lambda x: (-len(str(x.get("norm") or "")), -float(x.get("score") or 0.0))):
        field = str(item.get("field") or "")
        norm = str(item.get("norm") or "")
        if any(str(kept.get("field") or "") == field and norm in str(kept.get("norm") or "") for kept in filtered):
            continue
        if norm in seen_norms:
            continue
        seen_norms.add(norm)
        filtered.append(item)

    ranked = sorted(
        filtered,
        key=lambda x: (-float(x.get("score") or 0.0), -len(str(x.get("norm") or "")), str(x.get("field") or "")),
    )
    primary = ranked[0]
    aggregate = float(primary.get("score") or 0.0)
    aggregate += 0.5 * sum(float(item.get("score") or 0.0) for item in ranked[1:])
    aggregate = min(1.0, aggregate)

    fields = list(dict.fromkeys(str(item.get("field") or "") for item in ranked if str(item.get("field") or "")))
    values = [str(item.get("value") or "") for item in ranked if str(item.get("value") or "")]
    return {
        "field": str(primary.get("field") or ""),
        "value": str(primary.get("value") or ""),
        "score": round(float(aggregate), 6),
        "primary_score": round(float(primary.get("score") or 0.0), 6),
        "fields": fields[:8],
        "values": values[:8],
    }


def _float_or_default(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
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

    match_score = float(metadata_match.get("score") or 0.0)
    metadata_boost = match_score * max(0.0, float(phrase_boost_weight or 0.0))
    result["metadata_exact_match_score"] = match_score
    result["metadata_exact_match_primary_score"] = float(metadata_match.get("primary_score") or 0.0)
    result["metadata_exact_match_boost"] = float(metadata_boost)
    result["metadata_exact_match_field"] = str(metadata_match.get("field") or "")
    result["metadata_exact_match_value"] = str(metadata_match.get("value") or "")
    result["metadata_exact_match_fields"] = list(metadata_match.get("fields") or [])
    result["metadata_exact_match_values"] = list(metadata_match.get("values") or [])

    if promote_score:
        current_score = _float_or_default(result.get("score"), 0.0)
        promoted_score = max(current_score, match_score)
        if promoted_score > current_score:
            result["score"] = round(float(promoted_score), 6)
            result["metadata_exact_match_promoted_score"] = round(float(promoted_score), 6)
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
    return rows, annotated, promoted


def _metadata_exact_anchor_sort_key(
    row: tuple[Document, int],
    *,
    best_anchor_score: float,
) -> tuple[float, float, int]:
    doc, idx = row
    doc_meta = doc.metadata if isinstance(doc.metadata, dict) else {}
    metadata_score = _float_or_default(doc_meta.get("metadata_exact_match_score"), 0.0)
    score = _float_or_default(doc_meta.get("score"), 0.0)
    if best_anchor_score >= 0.65:
        return (-metadata_score, -score, int(idx))
    return (-score, -metadata_score, int(idx))


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
    rows, annotated, promoted = _annotate_anchor_docs(
        query=query,
        docs=docs,
        phrase_boost_weight=phrase_boost_weight,
    )
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
    rows.sort(key=lambda row: _metadata_exact_anchor_sort_key(row, best_anchor_score=best_anchor_score))
    out = [doc for doc, _idx in rows]
    after_top = _doc_key(out[0]) if out else ""
    meta["applied"] = True
    meta["annotated"] = int(annotated)
    meta["score_promoted"] = int(promoted)
    meta["top_changed"] = bool(before_top and after_top and before_top != after_top)
    meta["reason"] = "applied"
    return out, meta
