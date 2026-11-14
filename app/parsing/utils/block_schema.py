import re
from collections.abc import Mapping
from typing import Any

from app.parsing.utils.scalars import coerce_float as _coerce_float
from app.parsing.utils.scalars import coerce_int as _coerce_int
from app.rag.core.logging import get_logger

POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")

_KIND_ALIASES = {
    "": "paragraph",
    "text": "paragraph",
    "body": "paragraph",
    "para": "paragraph",
    "paragraph": "paragraph",
    "heading": "heading",
    "title": "heading",
    "list": "list",
    "bullet": "list",
    "table": "table",
    "image": "image",
    "figure": "image",
    "equation": "equation",
    "formula": "equation",
    "seal": "seal",
}


def block_bbox_value(element: Mapping[str, Any], key: str) -> float | None:
    bbox = element.get("bbox")
    if isinstance(bbox, Mapping):
        return _coerce_float(bbox.get(key))
    return None


def block_page(element: Mapping[str, Any]) -> int | None:
    page = _coerce_int(element.get("page"))
    if page is not None and page > 0:
        return page
    pages = element.get("pages")
    if isinstance(pages, list) and pages:
        first = _coerce_int(pages[0])
        if first is not None and first > 0:
            return first
    return None


def block_text(element: Mapping[str, Any]) -> str:
    value = element.get("text")
    if value is None:
        value = element.get("element_text")
    return str(value).strip() if value is not None else ""


def clean_position_tags(text: str) -> str:
    return POSITION_TAG_RE.sub("", text).strip()


def normalize_block_kind(kind: Any) -> str:
    key = kind.strip().lower() if isinstance(kind, str) else None
    return _KIND_ALIASES.get(key, "paragraph")


def parse_position_tags(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in POSITION_TAG_RE.finditer(text):
        pages: list[int] = []
        for token in match.group(1).split("-"):
            try:
                page = int(token)
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if page > 0 and page not in pages:
                pages.append(page)
        if not pages:
            continue
        left = float(match.group(2))
        right = float(match.group(3))
        top = float(match.group(4))
        bottom = float(match.group(5))
        out.append(
            {
                "tag": match.group(0),
                "page": pages[0],
                "pages": pages,
                "bbox": {
                    "x0": int(left),
                    "x1": int(right),
                    "y0": int(top),
                    "y1": int(bottom),
                },
            }
        )
    return out


def build_block_element(
    *,
    text: str,
    kind: Any,
    source_backend: str,
    source_element_id: str,
    element_id: str,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_kind = normalize_block_kind(kind)
    positions = parse_position_tags(text)
    first_position = positions[0] if positions else {}
    raw_kind = kind.strip().lower() if isinstance(kind, str) else None
    native_kind = raw_kind or normalized_kind
    merged_attributes: dict[str, Any] = {
        "source_backend": source_backend,
        "source_element_id": source_element_id,
        "source_content_type": native_kind,
        "source_doc_type": native_kind,
    }
    if attributes:
        merged_attributes.update(attributes)
    if positions:
        merged_attributes["position_tag"] = positions[0]["tag"]
        merged_attributes["position_tags"] = [item["tag"] for item in positions]

    element: dict[str, Any] = {
        "id": element_id,
        "kind": normalized_kind,
        "text": clean_position_tags(text),
        "page": first_position.get("page"),
        "pages": first_position.get("pages"),
        "bbox": first_position.get("bbox"),
        "source_backend": source_backend,
        "source_element_id": source_element_id,
        "attributes": merged_attributes,
    }
    confidence_value = merged_attributes.get("confidence")
    if confidence_value is None:
        confidence_value = merged_attributes.get("element_confidence")
    if confidence_value is None:
        confidence_value = merged_attributes.get("ocr_confidence")
    confidence = _coerce_float(confidence_value)
    if confidence is not None:
        element["confidence"] = max(0.0, min(1.0, confidence))
    return {key: value for key, value in element.items() if value not in (None, "", [])}


__all__ = [
    "POSITION_TAG_RE",
    "block_bbox_value",
    "block_page",
    "block_text",
    "build_block_element",
    "clean_position_tags",
    "normalize_block_kind",
    "parse_position_tags",
]
