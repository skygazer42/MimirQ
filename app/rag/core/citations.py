"""
Shared citation helpers.

These utilities convert retrieved LangChain `Document` objects into the
structured citation payload returned by both streaming and non-streaming RAG
pipelines.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.hashing import stable_json_hash
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.contracts import (
    DISPLAY_METADATA_KEY,
    EVALUABLE_METADATA_KEY,
    RECORD_IDENTITY_METADATA_KEY,
)

_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\d_+-]+|[\u4e00-\u9fff]{2,}")
_POSITION_TAG_RE = re.compile(r"@@([^#]+)##")
_SENTENCE_BOUNDARIES = {"。", "！", "？", ".", "!", "?", "\n"}
logger = get_logger(__name__)
_CITATION_FALLBACK_LOG_MESSAGE = "Ignoring non-critical citation fallback failure: %s"


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def _coerce_bbox(value: Any) -> dict[str, int] | None:
    if isinstance(value, dict):
        x0 = _coerce_int(value.get("x0"))
        y0 = _coerce_int(value.get("y0"))
        x1 = _coerce_int(value.get("x1"))
        y1 = _coerce_int(value.get("y1"))
        if None not in {x0, y0, x1, y1} and int(x1) > int(x0) and int(y1) > int(y0):
            return {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        x0, y0, x1, y1 = (_coerce_int(part) for part in value)
        if None not in {x0, y0, x1, y1} and int(x1) > int(x0) and int(y1) > int(y0):
            return {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}
    return None


def _extract_citation_bbox(meta: dict[str, Any]) -> dict[str, int] | None:
    for key in ("element_bbox", "source_bbox", "bbox", "seal_bbox"):
        bbox = _coerce_bbox(meta.get(key))
        if bbox is not None:
            return bbox
    for key in ("bboxes", "seal_bbox_list"):
        raw_list = meta.get(key)
        if not isinstance(raw_list, list):
            continue
        for item in raw_list:
            bbox = _coerce_bbox(item)
            if bbox is not None:
                return bbox
    return None


def _parse_position_tag_pages(raw_pages: str) -> int | None:
    first = str(raw_pages or "").split("-", 1)[0].strip()
    page = _coerce_int(first)
    return page if page is not None and page > 0 else None


def _position_tag_bbox_from_match(match: re.Match[str]) -> tuple[dict[str, int], int] | None:
    parts = match.group(1).split()
    if len(parts) < 5:
        return None
    page = _parse_position_tag_pages(parts[0])
    bbox = _coerce_bbox(
        {
            "x0": parts[1],
            "x1": parts[2],
            "y0": parts[3],
            "y1": parts[4],
        }
    )
    if page is None or bbox is None:
        return None
    return bbox, page


def _range_distance(start: int, end: int, target: int) -> int:
    if target < start:
        return start - target
    if target > end:
        return target - end
    return 0


def _target_midpoint(
    *,
    evidence_start: int | None,
    evidence_end: int | None,
) -> int | None:
    target_start = evidence_start if evidence_start is not None and evidence_start >= 0 else None
    if target_start is None:
        return None
    target_end = evidence_end if evidence_end is not None and evidence_end >= 0 else target_start
    return int((target_start + max(target_start, target_end)) / 2)


def _iter_position_tag_matches(raw: str) -> list[tuple[tuple[dict[str, int], int], int, int]]:
    matches: list[tuple[tuple[dict[str, int], int], int, int]] = []
    last_tag_end = 0
    for match in _POSITION_TAG_RE.finditer(raw):
        parsed = _position_tag_bbox_from_match(match)
        content_start = last_tag_end
        content_end = match.start()
        last_tag_end = match.end()
        if parsed is not None:
            matches.append((parsed, content_start, content_end))
    return matches


def _extract_position_tag_bbox(
    text: str,
    *,
    evidence_start: int | None = None,
    evidence_end: int | None = None,
) -> tuple[dict[str, int], int] | None:
    raw = str(text or "")
    if not raw:
        return None

    target_mid = _target_midpoint(
        evidence_start=evidence_start,
        evidence_end=evidence_end,
    )
    best: tuple[int, dict[str, int], int] | None = None
    for (bbox, page), content_start, content_end in _iter_position_tag_matches(raw):
        if target_mid is None:
            return bbox, page

        distance = _range_distance(content_start, content_end, target_mid)
        if best is None or distance < best[0]:
            best = (distance, bbox, page)
        if distance == 0:
            return bbox, page

    if best is None:
        return None
    return best[1], best[2]


def _iter_position_tag_strings(meta: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("element_text", "position_tagged_markdown"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)

    for key in ("attributes", "element_attributes"):
        attrs = meta.get(key)
        if not isinstance(attrs, dict):
            continue
        raw_tags = attrs.get("position_tags")
        if isinstance(raw_tags, list):
            values.extend(str(item or "") for item in raw_tags)
        raw_tag = attrs.get("position_tag")
        if isinstance(raw_tag, str) and raw_tag.strip():
            values.append(raw_tag)
    return values


def _extract_citation_bbox_with_page(
    meta: dict[str, Any],
    text: str,
    *,
    page_number: int | None,
    evidence_start: int | None,
    evidence_end: int | None,
) -> tuple[dict[str, int] | None, int | None, bool]:
    bbox = _extract_citation_bbox(meta)
    if bbox is not None:
        return bbox, _extract_bbox_page_number(meta, page_number), False

    found = _extract_position_tag_bbox(text, evidence_start=evidence_start, evidence_end=evidence_end)
    if found is not None:
        inline_bbox, inline_page = found
        return inline_bbox, inline_page, True

    for value in _iter_position_tag_strings(meta):
        found = _extract_position_tag_bbox(value)
        if found is not None:
            inline_bbox, inline_page = found
            return inline_bbox, inline_page, True

    return None, None, False


def _extract_page_number(meta: dict[str, Any]) -> int | None:
    for key in ("page", "page_number", "element_page"):
        value = _coerce_int(meta.get(key))
        if value is not None and value > 0:
            return int(value)
    page_index = _coerce_int(meta.get("page_index"))
    if page_index is not None and page_index >= 0:
        return int(page_index) + 1
    return None


def _extract_bbox_page_number(meta: dict[str, Any], fallback: int | None) -> int | None:
    for key in ("element_page", "page", "page_number"):
        value = _coerce_int(meta.get(key))
        if value is not None and value > 0:
            return int(value)
    page_index = _coerce_int(meta.get("page_index"))
    if page_index is not None and page_index >= 0:
        return int(page_index) + 1
    return fallback


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


def _find_prev_boundary(text: str, *, start: int, end: int) -> int:
    """Return the last sentence-boundary position in [start, end), or -1."""
    best = -1
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.rfind(ch, start, end)
        if pos > best:
            best = pos
    return best


def _find_next_boundary(text: str, *, start: int, end: int) -> int | None:
    """Return the first sentence-boundary position in [start, end), or None."""
    best: int | None = None
    for ch in _SENTENCE_BOUNDARIES:
        pos = text.find(ch, start, end)
        if pos < 0:
            continue
        if best is None or pos < best:
            best = pos
    return best


def _snippet_max_chars(max_chars: int) -> int:
    return max(60, int(max_chars or 0))


def _matched_terms_in_window(window: str, terms: list[str]) -> list[str]:
    folded = window.casefold()
    matched: list[str] = []
    for term in terms:
        if not term:
            continue
        term_s = str(term)
        haystack = folded if term_s.isascii() else window
        needle = term_s.casefold() if term_s.isascii() else term_s
        if needle in haystack:
            matched.append(term_s)
    return matched


def _sentence_window(raw: str, *, base_start: int, base_end: int, focus_start: int, focus_end: int) -> tuple[int, int]:
    start = base_start
    end = base_end
    prev = _find_prev_boundary(raw, start=base_start, end=focus_start)
    if prev >= 0:
        start = min(max(base_start, prev + 1), len(raw))
    nxt = _find_next_boundary(raw, start=focus_end, end=base_end)
    if nxt is not None:
        end = min(max(start, nxt + 1), len(raw))
    return start, end


def _snippet_text(raw: str, *, start: int, end: int, fallback_start: int, fallback_end: int) -> str:
    snippet = _collapse_ws(raw[start:end]).strip() or _collapse_ws(raw[fallback_start:fallback_end])
    if start > 0:
        snippet = "..." + snippet
    if end < len(raw):
        snippet += "..."
    return snippet


def _hit_window(raw: str, *, index: int, max_chars: int) -> tuple[int, int]:
    before = max_chars // 3
    after = max_chars - before
    return max(0, index - before), min(len(raw), index + after)


def _fallback_snippet_span(raw: str, *, max_chars: int) -> tuple[str, int, int]:
    base_end = min(len(raw), max_chars)
    end = base_end
    nxt = _find_next_boundary(raw, start=0, end=base_end)
    if nxt is not None and nxt > 0:
        end = min(base_end, nxt + 1)
    snippet = _collapse_ws(raw[:end]).strip() or _collapse_ws(raw[:base_end])
    if end < len(raw):
        snippet += "..."
    return snippet, 0, end


def _build_snippet_and_span(
    text: str,
    query: str | None,
    *,
    max_chars: int = 220,
) -> tuple[str, list[str], int | None, int | None]:
    """
    Build a human-friendly snippet for UI and (best-effort) raw span offsets into `text`.

    Offsets are only returned when we find a query-term hit; otherwise offsets are None.
    """
    max_chars = _snippet_max_chars(max_chars)
    raw = str(text or "")
    if not raw.strip():
        return "", [], None, None

    terms = _extract_query_terms(query or "", max_terms=10) if query else []
    hit = _find_first_match(raw, terms) if terms else None
    if hit is None:
        # Fallback: still return a bounded span window so the UI can deep-link/highlight
        # even when we don't find an explicit query-term match (best-effort).
        snippet, start, end = _fallback_snippet_span(raw, max_chars=max_chars)
        return snippet, [], int(start), int(end)

    idx, _ = hit
    base_start, base_end = _hit_window(raw, index=idx, max_chars=max_chars)
    start, end = _sentence_window(raw, base_start=base_start, base_end=base_end, focus_start=idx, focus_end=idx)
    snippet_raw = raw[start:end]
    snippet = _snippet_text(raw, start=start, end=end, fallback_start=base_start, fallback_end=base_end)
    matched = _matched_terms_in_window(snippet_raw, terms)

    return snippet, matched, int(start), int(end)


def _build_snippet_from_span(
    text: str,
    query: str | None,
    *,
    span_start: int,
    span_end: int,
    max_chars: int = 220,
) -> tuple[str, list[str]]:
    """
    Build a UI snippet anchored around a known local span (start/end in `text`).

    This is used for hierarchy context expansion so parent citations can point at the
    same evidence span as their anchor child (instead of the first query-term match).
    """
    max_chars = _snippet_max_chars(max_chars)
    raw = str(text or "")
    if not raw.strip():
        return "", []

    try:
        s = int(span_start)
        e = int(span_end)
    except Exception:
        return "", []

    s = max(0, min(s, len(raw)))
    e = max(s, min(e, len(raw)))
    if e <= s:
        return "", []

    terms = _extract_query_terms(query or "", max_terms=10) if query else []
    desired_len = min(len(raw), max_chars)

    # Keep the requested span inside the base window.
    base_start = max(0, min(s - (max_chars // 3), len(raw) - desired_len))
    base_end = min(len(raw), base_start + desired_len)
    if e > base_end:
        base_start = max(0, min(e - desired_len, len(raw) - desired_len))
        base_end = min(len(raw), base_start + desired_len)

    start, end = _sentence_window(raw, base_start=base_start, base_end=base_end, focus_start=s, focus_end=e)
    snippet_raw = raw[start:end]
    snippet = _snippet_text(raw, start=start, end=end, fallback_start=base_start, fallback_end=base_end)
    return snippet, _matched_terms_in_window(snippet_raw, terms)


_NIL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _is_uuid_like(v: Any) -> bool:
    if v is None:
        return False
    try:
        uuid.UUID(str(v))
        return True
    except Exception:
        return False


def _stable_tag_chunk_id(table_id: str | None) -> str:
    """
    Deterministic UUID for TAG-injected "docs" so ChatResponse citations remain schema-compatible.
    """
    tid = str(table_id or "").strip()
    return str(uuid.uuid5(_NIL_UUID, f"mimirq:tag:{tid}"))


def _parse_json_object(text: str) -> dict[str, Any] | None:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _tag_sheet_summary(payload: dict[str, Any]) -> str | None:
    sheet_name = payload.get("sheet_name")
    sheet_name = str(sheet_name).strip() if sheet_name is not None else ""
    sheet_index_i = _optional_int(payload.get("sheet_index"))
    if sheet_name:
        sheet_extra = f" (sheet_{sheet_index_i})" if sheet_index_i is not None else ""
        return f"Sheet: {sheet_name}{sheet_extra}"
    if sheet_index_i is not None:
        return f"Sheet: sheet_{sheet_index_i}"
    return None


def _tag_shape_summary(payload: dict[str, Any]) -> str | None:
    row_count_i = _optional_int(payload.get("row_count"))
    col_count_i = _optional_int(payload.get("col_count"))
    if row_count_i is None or col_count_i is None:
        return None
    return f"Shape: {row_count_i} rows x {col_count_i} cols"


def _tag_preview_rows(payload: dict[str, Any]) -> list[str]:
    columns = payload.get("columns") if isinstance(payload.get("columns"), list) else []
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    cols_s = [str(col) for col in columns if str(col).strip()][:6]
    if not cols_s or not rows:
        return []

    preview: list[str] = ["Rows (preview):"]
    for row in rows[:4]:
        if not isinstance(row, list):
            continue
        pairs = [f"{col}={str(row[i]).strip()}" for i, col in enumerate(cols_s) if i < len(row) and row[i] is not None and str(row[i]).strip()]
        if pairs:
            preview.append("- " + ", ".join(pairs))
    return preview


def _format_tag_table_store_summary(doc: Document, *, meta: dict[str, Any]) -> str | None:
    """
    Convert a TAG table_store JSON payload into a human-readable summary for citations/UI.
    """
    payload = _parse_json_object(doc.page_content or "")
    if not payload:
        return None
    if str(payload.get("kind") or "") != "tag_table_store":
        return None

    doc_name = str(payload.get("document") or meta.get("source") or "table").strip() or "table"
    table_id = str(payload.get("table_id") or meta.get("table_id") or "").strip()

    sql = str(payload.get("sql") or "").strip()
    truncated = bool(payload.get("truncated"))

    parts: list[str] = ["[TAG] Table Query Result"]
    parts.append(f"Document: {doc_name}")
    for summary in (_tag_sheet_summary(payload), _tag_shape_summary(payload)):
        if summary:
            parts.append(summary)
    if table_id:
        parts.append(f"Table ID: {table_id}")
    if sql:
        parts.append(f"SQL: {sql}")
    parts.extend(_tag_preview_rows(payload))
    if truncated:
        parts.append("(truncated)")

    return "\n".join(parts).strip() or None


def _bounded_str(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _safe_kg_path_item(raw: Any, *, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    item: dict[str, Any] = {}
    kind = _bounded_str(raw.get("kind"), limit=30)
    if kind:
        item["kind"] = kind
    for key in keys:
        value = _bounded_str(raw.get(key), limit=200)
        if value:
            item[key] = value
    return item or None


def _safe_kg_path_items(raw: Any, *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    items: list[dict[str, Any]] = []
    for entry_raw in raw:
        entry = _safe_kg_path_item(entry_raw, keys=keys)
        if entry:
            items.append(entry)
        if len(items) >= 10:
            break
    return items


def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
    """
    Sanitize a shortest-path provenance payload for citations.

    Keeps identifiers and small, low-cardinality fields only; drops text evidence.
    """
    if not isinstance(raw, dict) or not raw:
        return None

    out: dict[str, Any] = {}
    for key, limit in (("schema", 80), ("kind", 50)):
        value = _bounded_str(raw.get(key), limit=limit)
        if value:
            out[key] = value
    try:
        if raw.get("hops") is not None:
            out["hops"] = int(raw.get("hops") or 0)
    except Exception as exc:
        logger.debug(_CITATION_FALLBACK_LOG_MESSAGE, exc)

    nodes = _safe_kg_path_items(
        raw.get("nodes"),
        keys=("entity_id", "type", "event_id", "document_id", "chunk_id"),
    )
    if nodes:
        out["nodes"] = nodes

    edges = _safe_kg_path_items(
        raw.get("edges"),
        keys=(
            "entity_id",
            "event_id",
            "document_id",
            "chunk_id",
            "relation_id",
            "predicate",
            "confidence_bucket",
            "evidence_source",
        ),
    )
    if edges:
        out["edges"] = edges

    return out or None


@dataclass
class _CitationContext:
    meta: dict[str, Any]
    tag_payload: dict[str, Any] | None
    effective_text: str
    chunk_id: Any
    retrieval_role: str | None
    neighbor_of: str | None
    is_tag: bool
    is_image: bool
    hit_type: str
    img_id: Any
    img_url: str | None
    clean_docx_url: str | None
    page_number: int | None
    start_char: int | None
    end_char: int | None
    chunk_index: int | None
    snippet: str
    matched_terms: list[str]
    evidence_start_in_chunk: int | None
    evidence_end_in_chunk: int | None
    bbox: dict[str, int] | None
    bbox_page_number: int | None
    hierarchy_basis: str | None
    hierarchy_family_key: str | None
    family_collapse_key: str | None
    family_hit: bool
    scores: dict[str, Any]


def _float_meta(meta: dict[str, Any], key: str) -> float:
    try:
        return float(meta.get(key, 0.0) or 0.0)
    except Exception:
        return 0.0


def _rounded_optional(value: Any, *, digits: int) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except Exception as exc:
        logger.debug(_CITATION_FALLBACK_LOG_MESSAGE, exc)
        return None


def _optional_clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _citation_scores(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "vector_score": _float_meta(meta, "vector_score"),
        "bm25_score": _float_meta(meta, "bm25_score"),
        "lexical_score": _float_meta(meta, "lexical_score"),
        "sparse_score": _float_meta(meta, "sparse_score"),
        "colbert_score": _float_meta(meta, "colbert_score"),
        "rerank_score": meta.get("rerank_score"),
        "retrieval_score": meta.get("retrieval_score"),
        "rerank_score_calibrated": meta.get("rerank_score_calibrated"),
        "rerank_score_final": meta.get("rerank_score_final"),
        "exact_phrase_score": meta.get("exact_phrase_score"),
        "exact_phrase_boost": meta.get("exact_phrase_boost"),
        "metadata_exact_match_score": meta.get("metadata_exact_match_score"),
        "metadata_exact_match_boost": meta.get("metadata_exact_match_boost"),
    }


def _citation_plugin_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for view_key in (DISPLAY_METADATA_KEY, EVALUABLE_METADATA_KEY):
        view = meta.get(view_key)
        if not isinstance(view, dict) or not view:
            continue
        out.update(view)
        out[view_key] = dict(view)

    record_identity = meta.get(RECORD_IDENTITY_METADATA_KEY)
    if isinstance(record_identity, dict) and record_identity:
        out[RECORD_IDENTITY_METADATA_KEY] = dict(record_identity)
    return out


def _hit_type(*, scores: dict[str, Any], retrieval_mode: str, retrieval_role: str | None, is_image: bool) -> str:
    if str(retrieval_role or "").strip().lower() == "tag":
        hit_type = "tag"
    elif is_image:
        hit_type = "image"
    elif retrieval_mode == "mmr":
        hit_type = "mmr"
    else:
        vector_score = float(scores["vector_score"])
        bm25_score = float(scores["bm25_score"])
        colbert_score = float(scores["colbert_score"])
        max_dense = max(vector_score, bm25_score, float(scores["lexical_score"]), float(scores["sparse_score"]))
        if colbert_score > max_dense:
            hit_type = "colbert_ann"
        elif vector_score > bm25_score:
            hit_type = "vector"
        elif bm25_score > vector_score:
            hit_type = "keyword"
        else:
            hit_type = "hybrid"
    return hit_type


def _media_urls(meta: dict[str, Any]) -> tuple[Any, str | None, str | None]:
    img_id = meta.get("img_id")
    img_url = f"/api/v1/documents/image-url/{img_id}" if img_id else _optional_clean_str(meta.get("img_url") or meta.get("image_url"))

    clean_docx_url = _optional_clean_str(meta.get("clean_docx_url"))
    doc_id_for_clean = meta.get("document_id")
    doc_name_for_clean = str(meta.get("source") or meta.get("document_name") or "").strip().lower()
    file_type_for_clean = str(meta.get("file_type") or "").strip().lower()
    if clean_docx_url or doc_id_for_clean is None or not (doc_name_for_clean.endswith(".docx") or file_type_for_clean == "docx"):
        return img_id, img_url, clean_docx_url
    return img_id, img_url, f"/api/v1/documents/{doc_id_for_clean}/clean-docx"


def _resolve_chunk_id(doc: Document, meta: dict[str, Any], *, is_tag: bool, tag_payload: dict[str, Any] | None) -> Any:
    chunk_id = getattr(doc, "id", None) or meta.get("chunk_id")
    if not is_tag or _is_uuid_like(chunk_id):
        return chunk_id

    tag_table_id = str(meta.get("table_id") or "").strip()
    if not tag_table_id and tag_payload:
        tag_table_id = str(tag_payload.get("table_id") or "").strip()
    return _stable_tag_chunk_id(tag_table_id)


def _effective_citation_text(doc: Document, meta: dict[str, Any], *, is_tag: bool) -> str:
    effective_text = doc.page_content or ""
    if is_tag:
        formatted = _format_tag_table_store_summary(doc, meta=meta)
        if formatted:
            return formatted
    return effective_text


def _optional_meta_int(meta: dict[str, Any], key: str) -> int | None:
    try:
        value = meta.get(key)
        return int(value) if value is not None else None
    except Exception:
        return None


def _family_keys(meta: dict[str, Any]) -> tuple[str | None, str | None, str | None, bool]:
    hierarchy_basis = _optional_clean_str(meta.get("hierarchy_basis"))
    hierarchy_family_key = _optional_clean_str(meta.get("hierarchy_family_key"))
    family_collapse_key = hierarchy_family_key or _optional_clean_str(meta.get("parent_id")) or _optional_clean_str(meta.get("parent_node_id"))
    return hierarchy_basis, hierarchy_family_key, family_collapse_key, bool(family_collapse_key)


def _citation_context(
    doc: Document,
    *,
    retrieval_mode: str,
    query: str | None,
) -> _CitationContext:
    meta = doc.metadata or {}
    retrieval_role = _optional_clean_str(meta.get("retrieval_role"))
    neighbor_of = _optional_clean_str(meta.get("neighbor_of"))
    is_tag = str(retrieval_role or "").strip().lower() == "tag" or str(meta.get("chunk_role") or "") == "tag_sql_result"
    is_image = str(retrieval_role or "").strip().lower() == "image" or str(meta.get("doc_type_kwd") or "").strip().lower() == "image"
    tag_payload = _parse_json_object(doc.page_content or "") if is_tag else None
    scores = _citation_scores(meta)
    chunk_id = _resolve_chunk_id(doc, meta, is_tag=is_tag, tag_payload=tag_payload)
    effective_text = _effective_citation_text(doc, meta, is_tag=is_tag)
    snippet, matched_terms, evidence_start, evidence_end = _build_snippet_and_span(effective_text, query, max_chars=220)
    page_number = _extract_page_number(meta)
    bbox, bbox_page_number, bbox_from_position_tag = _extract_citation_bbox_with_page(
        meta,
        effective_text,
        page_number=page_number,
        evidence_start=evidence_start,
        evidence_end=evidence_end,
    )
    if bbox_from_position_tag and bbox_page_number is not None:
        page_number = bbox_page_number
    hierarchy_basis, hierarchy_family_key, family_collapse_key, family_hit = _family_keys(meta)
    img_id, img_url, clean_docx_url = _media_urls(meta)
    return _CitationContext(
        meta=meta,
        tag_payload=tag_payload,
        effective_text=effective_text,
        chunk_id=chunk_id,
        retrieval_role=retrieval_role,
        neighbor_of=neighbor_of,
        is_tag=is_tag,
        is_image=is_image,
        hit_type=_hit_type(scores=scores, retrieval_mode=retrieval_mode, retrieval_role=retrieval_role, is_image=is_image),
        img_id=img_id,
        img_url=img_url,
        clean_docx_url=clean_docx_url,
        page_number=page_number,
        start_char=_optional_meta_int(meta, "start_char"),
        end_char=_optional_meta_int(meta, "end_char"),
        chunk_index=_optional_meta_int(meta, "chunk_index"),
        snippet=snippet,
        matched_terms=matched_terms,
        evidence_start_in_chunk=evidence_start,
        evidence_end_in_chunk=evidence_end,
        bbox=bbox,
        bbox_page_number=bbox_page_number,
        hierarchy_basis=hierarchy_basis,
        hierarchy_family_key=hierarchy_family_key,
        family_collapse_key=family_collapse_key,
        family_hit=family_hit,
        scores=scores,
    )


def _absolute_evidence(start_char: int | None, local_offset: int | None) -> int | None:
    if start_char is None or local_offset is None:
        return None
    return int(start_char) + int(local_offset)


def _base_citation(
    ctx: _CitationContext,
    *,
    retrieval_elapsed_sec: float,
    retrieval_mode: str,
) -> dict[str, Any]:
    meta = ctx.meta
    scores = ctx.scores
    return {
        "chunk_id": ctx.chunk_id,
        "dataset_id": meta.get("dataset_id"),
        "document_id": meta.get("document_id"),
        "document_name": meta.get("source", "Unknown"),
        "chunk_content": ctx.snippet or ((ctx.effective_text or "")[:200] + "..."),
        "metadata": _citation_plugin_metadata(meta),
        "matched_terms": ctx.matched_terms,
        "page_number": ctx.page_number,
        "chunk_index": ctx.chunk_index,
        "start_char": ctx.start_char,
        "end_char": ctx.end_char,
        "evidence_start_char": _absolute_evidence(ctx.start_char, ctx.evidence_start_in_chunk),
        "evidence_end_char": _absolute_evidence(ctx.start_char, ctx.evidence_end_in_chunk),
        "header_path": meta.get("header_path") or meta.get("header_context"),
        "chunk_strategy": meta.get("chunk_strategy"),
        "chunk_role": meta.get("chunk_role"),
        "chunk_semantic_role": meta.get("chunk_semantic_role"),
        "policy_clause_id": meta.get("policy_clause_id"),
        "policy_clause_number": meta.get("policy_clause_number"),
        "policy_path": meta.get("policy_path"),
        "policy_path_str": meta.get("policy_path_str"),
        "parent_id": meta.get("parent_id"),
        "hierarchy_basis": ctx.hierarchy_basis,
        "hierarchy_family_key": ctx.hierarchy_family_key,
        "family_collapse_key": ctx.family_collapse_key,
        "family_hit": ctx.family_hit,
        "retrieval_role": ctx.retrieval_role,
        "neighbor_of": ctx.neighbor_of,
        "doc_pipeline_key": meta.get("doc_pipeline_key"),
        "pipeline_hash": meta.get("pipeline_hash"),
        "relevance_score": round(float(meta.get("score", 0.0) or 0.0), 2),
        "vector_score": round(float(scores["vector_score"]), 3),
        "bm25_score": round(float(scores["bm25_score"]), 3),
        "lexical_score": round(float(scores["lexical_score"]), 3),
        "sparse_score": round(float(scores["sparse_score"]), 3),
        "colbert_score": round(float(scores["colbert_score"]), 3),
        "keyword_score": round(_float_meta(meta, "keyword_score"), 3),
        "field_aware_signal": str(meta.get("field_aware_signal")).strip().lower() if meta.get("field_aware_signal") is not None else None,
        "field_aware_boost": round(_float_meta(meta, "field_aware_boost"), 6),
        "kg_pagerank": round(_float_meta(meta, "kg_pagerank"), 3),
        "kg_shared_events": int(meta.get("kg_shared_events", 0) or 0),
        "kg_path_length": int(meta.get("kg_path_length", 0) or 0),
        "kg_edge_conf_low": round(_float_meta(meta, "kg_edge_conf_low"), 3),
        "kg_edge_conf_mid": round(_float_meta(meta, "kg_edge_conf_mid"), 3),
        "kg_edge_conf_high": round(_float_meta(meta, "kg_edge_conf_high"), 3),
        "kg_evidence_anchored": bool(meta.get("kg_evidence_anchored", False)),
        "kg_boost_applied": bool(meta.get("kg_boost_applied", False)),
        "kg_boost_score": _rounded_optional(meta.get("kg_boost_score"), digits=6),
        "rerank_score": _rounded_optional(scores.get("rerank_score"), digits=3),
        "retrieval_score": _rounded_optional(scores.get("retrieval_score"), digits=3),
        "rerank_score_calibrated": _rounded_optional(scores.get("rerank_score_calibrated"), digits=6),
        "rerank_score_final": _rounded_optional(scores.get("rerank_score_final"), digits=6),
        "exact_phrase_score": _rounded_optional(scores.get("exact_phrase_score"), digits=6),
        "exact_phrase_boost": _rounded_optional(scores.get("exact_phrase_boost"), digits=6),
        "metadata_exact_match_score": _rounded_optional(scores.get("metadata_exact_match_score"), digits=6),
        "metadata_exact_match_boost": _rounded_optional(scores.get("metadata_exact_match_boost"), digits=6),
        "metadata_exact_match_field": meta.get("metadata_exact_match_field"),
        "reranker_provider": meta.get("reranker_provider"),
        "rerank_elapsed_sec": meta.get("rerank_elapsed_sec"),
        "rerank_model_used": meta.get("rerank_model_used"),
        "retrieval_mode": retrieval_mode,
        "vector_backend": getattr(settings, "VECTOR_BACKEND", "unknown"),
        "retrieval_elapsed_sec": round(float(retrieval_elapsed_sec or 0.0), 3),
        "hit_type": ctx.hit_type,
    }


def _tag_payload_value(ctx: _CitationContext, key: str) -> Any:
    value = ctx.meta.get(key)
    if value is None and ctx.tag_payload:
        value = ctx.tag_payload.get(key)
    return value


def _tag_schema_link_values(ctx: _CitationContext) -> tuple[Any, Any]:
    score = ctx.meta.get("schema_link_score")
    strategy = ctx.meta.get("schema_link_strategy")
    diagnostics = ctx.meta.get("schema_link_diagnostics")
    if isinstance(diagnostics, dict):
        score = diagnostics.get("score") if score is None else score
        strategy = diagnostics.get("strategy") if strategy is None else strategy
    if ctx.tag_payload:
        score = ctx.tag_payload.get("schema_link_score") if score is None else score
        strategy = ctx.tag_payload.get("schema_link_strategy") if strategy is None else strategy
        payload_schema_link = ctx.tag_payload.get("schema_link")
        if isinstance(payload_schema_link, dict):
            score = payload_schema_link.get("score") if score is None else score
            strategy = payload_schema_link.get("strategy") if strategy is None else strategy
    return score, strategy


def _tag_row_source_values(ctx: _CitationContext) -> tuple[Any, Any, Any]:
    table = ctx.meta.get("row_source_table")
    sync_token = ctx.meta.get("row_source_sync_token")
    pk_hashes = ctx.meta.get("row_source_pk_hashes")
    payload_row_source = ctx.tag_payload.get("row_source") if ctx.tag_payload else None
    if isinstance(payload_row_source, dict):
        table = payload_row_source.get("table") if table is None else table
        sync_token = payload_row_source.get("sync_token") if sync_token is None else sync_token
        pk_hashes = payload_row_source.get("pk_hashes") if pk_hashes is None else pk_hashes
    return table, sync_token, pk_hashes


def _limited_unique_strings(raw: Any, *, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value and value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _safe_join_provenance(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    items: list[dict[str, Any]] = []
    for entry_raw in raw:
        if not isinstance(entry_raw, dict):
            continue
        item = {
            key: str(entry_raw.get(key)).strip()[:160]
            for key in ("left_table", "left_column", "right_table", "right_column", "reason")
            if entry_raw.get(key) is not None and str(entry_raw.get(key)).strip()
        }
        confidence = _rounded_optional(entry_raw.get("confidence"), digits=6)
        if confidence is not None:
            item["confidence"] = confidence
        if item:
            items.append(item)
        if len(items) >= 10:
            break
    return items


def _apply_tag_identity_fields(citation: dict[str, Any], ctx: _CitationContext) -> None:
    for output_key, value in (
        ("table_id", _tag_payload_value(ctx, "table_id")),
        ("sheet_index", _tag_payload_value(ctx, "sheet_index")),
        ("sheet_name", _tag_payload_value(ctx, "sheet_name")),
        ("sql_generation_mode", _tag_payload_value(ctx, "sql_generation_mode")),
    ):
        if value is not None:
            citation[output_key] = value


def _apply_tag_schema_fields(citation: dict[str, Any], ctx: _CitationContext) -> None:
    schema_link_score, schema_link_strategy = _tag_schema_link_values(ctx)
    score = _rounded_optional(schema_link_score, digits=6)
    if score is not None:
        citation["tag_schema_link_score"] = score
    if schema_link_strategy is not None:
        citation["tag_schema_link_strategy"] = str(schema_link_strategy)[:80]


def _apply_tag_row_source_fields(citation: dict[str, Any], ctx: _CitationContext) -> None:
    row_source_table, row_source_sync_token, row_source_pk_hashes = _tag_row_source_values(ctx)
    if row_source_table is not None:
        citation["row_source_table"] = str(row_source_table)[:300]
    if row_source_sync_token is not None:
        citation["row_source_sync_token"] = str(row_source_sync_token)[:300]
    row_hashes = _limited_unique_strings(row_source_pk_hashes, limit=200)
    if row_hashes:
        citation["row_source_pk_hashes"] = row_hashes


def _apply_tag_join_fields(citation: dict[str, Any], ctx: _CitationContext) -> None:
    join_provenance = ctx.meta.get("join_provenance")
    join_table_ids = ctx.meta.get("join_table_ids")
    if ctx.tag_payload:
        join_provenance = ctx.tag_payload.get("join_provenance") if join_provenance is None else join_provenance
        join_table_ids = ctx.tag_payload.get("join_table_ids") if join_table_ids is None else join_table_ids
    safe_join = _safe_join_provenance(join_provenance)
    if safe_join:
        citation["join_provenance"] = safe_join
    table_ids = _limited_unique_strings(join_table_ids, limit=10)
    if table_ids:
        citation["join_table_ids"] = table_ids


def _apply_tag_fields(citation: dict[str, Any], ctx: _CitationContext) -> None:
    if not ctx.is_tag:
        return

    _apply_tag_identity_fields(citation, ctx)
    _apply_tag_schema_fields(citation, ctx)
    _apply_tag_row_source_fields(citation, ctx)
    _apply_tag_join_fields(citation, ctx)


def _kg_path_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    path: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ent_id = _optional_clean_str(item.get("entity_id"))
        if not ent_id:
            continue
        entry: dict[str, Any] = {"entity_id": ent_id}
        typ = _optional_clean_str(item.get("type"))
        if typ:
            entry["type"] = typ[:100]
        path.append(entry)
        if len(path) >= 6:
            break
    return path


def _apply_kg_fields(citation: dict[str, Any], meta: dict[str, Any]) -> None:
    kg_path = _kg_path_entries(meta.get("kg_path"))
    if kg_path:
        citation["kg_path"] = kg_path
    provenance = _safe_kg_path_provenance(meta.get("kg_path_provenance"))
    if provenance:
        citation["kg_path_provenance"] = provenance


def _apply_media_fields(citation: dict[str, Any], ctx: _CitationContext) -> None:
    has_image = bool(ctx.img_id) or bool(ctx.img_url)
    if ctx.img_id:
        citation["img_id"] = ctx.img_id
    if ctx.img_url:
        citation["img_url"] = ctx.img_url
    if ctx.clean_docx_url:
        citation["clean_docx_url"] = ctx.clean_docx_url
    citation["has_image"] = bool(has_image)


def _apply_hashes(citation: dict[str, Any]) -> None:
    anchor_payload = {
        "document_id": citation.get("document_id"),
        "chunk_id": citation.get("chunk_id"),
        "page_number": citation.get("page_number"),
        "chunk_index": citation.get("chunk_index"),
        "start_char": citation.get("start_char"),
        "end_char": citation.get("end_char"),
        "retrieval_role": citation.get("retrieval_role"),
        "table_id": citation.get("table_id"),
        "row_source_table": citation.get("row_source_table"),
        "row_source_sync_token": citation.get("row_source_sync_token"),
        "row_source_pk_hashes": citation.get("row_source_pk_hashes"),
    }
    if citation.get("bbox") is not None:
        anchor_payload["bbox"] = citation.get("bbox")
        anchor_payload["bbox_page_number"] = citation.get("bbox_page_number")
    citation["evidence_anchor_hash"] = stable_json_hash(anchor_payload, length=16)
    citation["citation_hash"] = stable_json_hash(citation, length=16)


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _hierarchy_anchor_span(parent: dict[str, Any], anchor: dict[str, Any]) -> tuple[int, int, int] | None:
    doc_a = str(anchor.get("document_id") or "").strip()
    doc_b = str(parent.get("document_id") or "").strip()
    if doc_a and doc_b and doc_a != doc_b:
        return None

    parent_start = _to_int(parent.get("start_char"))
    parent_end = _to_int(parent.get("end_char"))
    anchor_start = _to_int(anchor.get("evidence_start_char"))
    anchor_end = _to_int(anchor.get("evidence_end_char"))
    if parent_start is None or anchor_start is None or anchor_end is None or anchor_end <= anchor_start:
        return None
    if anchor_start < parent_start or (parent_end is not None and anchor_end > parent_end):
        return None
    return parent_start, anchor_start, anchor_end


def _merge_hierarchy_parent_spans(
    citations: list[dict[str, Any]],
    *,
    raw_text_by_chunk_id: dict[str, str],
    query: str | None,
) -> None:
    by_chunk = {str(c.get("chunk_id")).strip(): c for c in citations if isinstance(c, dict) and c.get("chunk_id") is not None}
    for citation in citations:
        if str(citation.get("retrieval_role") or "").strip().lower() != "hierarchy_parent":
            continue
        anchor = by_chunk.get(str(citation.get("neighbor_of") or "").strip())
        if not isinstance(anchor, dict):
            continue
        span = _hierarchy_anchor_span(citation, anchor)
        if span is None:
            continue
        parent_start, anchor_start, anchor_end = span
        citation["evidence_start_char"] = int(anchor_start)
        citation["evidence_end_char"] = int(anchor_end)
        text = raw_text_by_chunk_id.get(str(citation.get("chunk_id") or "").strip())
        if not text:
            continue
        snippet, matched = _build_snippet_from_span(
            text,
            query,
            span_start=int(anchor_start) - int(parent_start),
            span_end=int(anchor_end) - int(parent_start),
            max_chars=220,
        )
        if snippet:
            citation["chunk_content"] = snippet
        if matched:
            citation["matched_terms"] = matched


def build_citations_from_docs(
    docs: list[Document],
    *,
    retrieval_elapsed_sec: float,
    retrieval_mode: str,
    query: str | None = None,
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    # Used for hierarchy span merging; keeps only per-chunk text already being used to
    # build citations (so no extra DB calls or content retention outside this function).
    raw_text_by_chunk_id: dict[str, str] = {}
    for doc in docs:
        ctx = _citation_context(doc, retrieval_mode=retrieval_mode, query=query)
        chunk_id_s = str(ctx.chunk_id).strip() if ctx.chunk_id is not None else ""
        if chunk_id_s:
            raw_text_by_chunk_id.setdefault(chunk_id_s, str(ctx.effective_text or ""))

        citation = _base_citation(ctx, retrieval_elapsed_sec=retrieval_elapsed_sec, retrieval_mode=retrieval_mode)
        if ctx.bbox is not None:
            citation["bbox"] = ctx.bbox
            citation["bbox_page_number"] = ctx.bbox_page_number
        _apply_tag_fields(citation, ctx)
        _apply_kg_fields(citation, ctx.meta)
        _apply_media_fields(citation, ctx)
        _apply_hashes(citation)
        citations.append(citation)

    try:
        _merge_hierarchy_parent_spans(citations, raw_text_by_chunk_id=raw_text_by_chunk_id, query=query)
    except Exception as exc:
        logger.debug(_CITATION_FALLBACK_LOG_MESSAGE, exc)

    return citations
