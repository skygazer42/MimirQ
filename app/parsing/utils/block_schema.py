from __future__ import annotations

import re
from typing import Any

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


def clean_position_tags(text: Any) -> str:
    return POSITION_TAG_RE.sub("", str(text or "")).strip()


def normalize_block_kind(kind: Any) -> str:
    return _KIND_ALIASES.get(str(kind or "").strip().lower(), "paragraph")


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


def parse_position_tags(text: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in POSITION_TAG_RE.finditer(str(text or "")):
        pages: list[int] = []
        for token in str(match.group(1) or "").split("-"):
            try:
                page = int(token)
            except Exception:
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
    text: Any,
    kind: Any,
    source_backend: str,
    source_element_id: str,
    element_id: str,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_kind = normalize_block_kind(kind)
    positions = parse_position_tags(text)
    first_position = positions[0] if positions else {}
    native_kind = str(kind or "").strip().lower() or normalized_kind
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
    confidence = _coerce_float(
        merged_attributes.get("confidence")
        if merged_attributes.get("confidence") is not None
        else merged_attributes.get("element_confidence")
        if merged_attributes.get("element_confidence") is not None
        else merged_attributes.get("ocr_confidence")
    )
    if confidence is not None:
        element["confidence"] = max(0.0, min(1.0, float(confidence)))
    return {key: value for key, value in element.items() if value not in (None, "", [])}


__all__ = [
    "POSITION_TAG_RE",
    "build_block_element",
    "clean_position_tags",
    "normalize_block_kind",
    "parse_position_tags",
]
