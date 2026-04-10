from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from langchain_core.documents import Document

_KNOWN_KINDS = {"heading", "paragraph", "list", "table", "image", "equation", "seal"}
_POSITION_TAG_RE = re.compile(r"@@[0-9-]+\t[0-9.]+\t[0-9.]+\t[0-9.]+\t[0-9.]+##")
_SKIP_ATTRIBUTE_KEYS = {
    "image",
    "images",
    "bbox",
    "bboxes",
    "element_bbox",
    "element_kind",
    "element_text",
    "element_page",
    "element_confidence",
    "element_attributes",
    "seal_bbox",
    "seal_bbox_list",
    "position_tagged_markdown",
}


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if number != number:
            return None
        return float(number)
    except Exception:
        return None


def _get_metadata(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        meta = item.get("metadata")
    else:
        meta = getattr(item, "metadata", None)
    return dict(meta) if isinstance(meta, Mapping) else {}


def _get_text(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("page_content") or "")
    return str(getattr(item, "page_content", "") or "")


def _clean_element_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return _POSITION_TAG_RE.sub("", text).strip()


def _coerce_bbox(value: Any) -> dict[str, int] | None:
    if isinstance(value, Mapping):
        x0 = _coerce_int(value.get("x0"))
        y0 = _coerce_int(value.get("y0"))
        x1 = _coerce_int(value.get("x1"))
        y1 = _coerce_int(value.get("y1"))
        if None not in {x0, y0, x1, y1}:
            return {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        x0, y0, x1, y1 = (_coerce_int(part) for part in value)
        if None not in {x0, y0, x1, y1}:
            return {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}
    return None


def _extract_bbox(meta: Mapping[str, Any]) -> dict[str, int] | None:
    bbox = _coerce_bbox(meta.get("element_bbox"))
    if bbox is not None:
        return bbox
    for key in ("seal_bbox", "bbox"):
        bbox = _coerce_bbox(meta.get(key))
        if bbox is not None:
            return bbox
    bboxes = meta.get("bboxes")
    if isinstance(bboxes, list) and bboxes:
        bbox = _coerce_bbox(bboxes[0])
        if bbox is not None:
            return bbox
    seal_bbox_list = meta.get("seal_bbox_list")
    if isinstance(seal_bbox_list, list) and seal_bbox_list:
        bbox = _coerce_bbox(seal_bbox_list[0])
        if bbox is not None:
            return bbox
    return None


def _extract_page(meta: Mapping[str, Any]) -> int | None:
    value = _coerce_int(meta.get("element_page"))
    if value is not None:
        return int(value)
    for key in ("page", "page_number", "page_index"):
        value = _coerce_int(meta.get(key))
        if value is None:
            continue
        if key == "page_index":
            return int(value) + 1
        return int(value)
    pages = meta.get("pages")
    if isinstance(pages, list) and pages:
        first = _coerce_int(pages[0])
        if first is not None:
            return int(first) + 1 if int(first) == 0 else int(first)
    return None


def _classify_kind(meta: Mapping[str, Any], text: str) -> str:
    preferred = str(meta.get("element_kind") or "").strip().lower()
    if preferred in _KNOWN_KINDS:
        return preferred

    for raw in (meta.get("doc_type_kwd"), meta.get("content_type")):
        value = str(raw or "").strip().lower()
        if value in _KNOWN_KINDS:
            return value
        if value in {"text", "ocr"}:
            break

    chunk_role = str(meta.get("chunk_role") or "").strip().lower()
    if chunk_role in _KNOWN_KINDS:
        return chunk_role
    if chunk_role == "ocr":
        return "unknown"

    stripped = text.strip()
    if not stripped:
        return "unknown"
    return "paragraph"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            safe_item = _json_safe(item)
            if safe_item is not None:
                out[str(key)] = safe_item
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            safe_item = _json_safe(item)
            if safe_item is not None:
                out.append(safe_item)
        return out
    return None


def _extract_attributes(meta: Mapping[str, Any]) -> dict[str, Any] | None:
    attrs: dict[str, Any] = {}
    preferred_attrs = meta.get("element_attributes")
    if isinstance(preferred_attrs, Mapping):
        safe_preferred = _json_safe(dict(preferred_attrs))
        if isinstance(safe_preferred, dict):
            attrs.update(safe_preferred)
    for key, value in meta.items():
        if key in _SKIP_ATTRIBUTE_KEYS:
            continue
        if key in {"page", "page_number", "page_index"}:
            continue
        safe_value = _json_safe(value)
        if safe_value is not None:
            attrs[str(key)] = safe_value
    return attrs or None


def normalize_document_elements(items: Iterable[Document | Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items or []):
        meta = _get_metadata(item)
        text = _clean_element_text(meta.get("element_text")) or _get_text(item)
        kind = _classify_kind(meta, text)
        page = _extract_page(meta)
        bbox = _extract_bbox(meta)
        confidence = None
        for key in ("element_confidence", "seal_score", "confidence", "score"):
            confidence = _coerce_float(meta.get(key))
            if confidence is not None:
                break

        item_id = str(meta.get("element_id") or meta.get("id") or "").strip()
        if not item_id:
            page_part = str(page) if page is not None else "na"
            item_id = f"{kind}:{page_part}:{index}"

        out.append(
            {
                "id": item_id,
                "kind": kind,
                "page": page,
                "text": text or None,
                "bbox": bbox,
                "confidence": confidence,
                "attributes": _extract_attributes(meta),
            }
        )
    return out


__all__ = ["normalize_document_elements"]
