import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.documents import Document

from app.parsing.utils.scalars import coerce_float as _coerce_float
from app.parsing.utils.scalars import coerce_int as _coerce_int

_KNOWN_KINDS = {"heading", "paragraph", "list", "table", "image", "equation", "seal"}
_POSITION_TAG_RE = re.compile(r"@@[0-9-]+\t[0-9.]+\t[0-9.]+\t[0-9.]+\t[0-9.]+##")
_POSITION_TAG_DETAIL_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")
_MD_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
    re.IGNORECASE,
)
_HTML_IMAGE_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"][^>]*>", re.IGNORECASE)
_HTML_ALT_RE = re.compile(r"\balt\s*=\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
_DISPLAY_MATH_RE = re.compile(r"^\s*(\$\$.*\$\$|\\\[.*\\\])\s*$", re.DOTALL)
_SKIP_ATTRIBUTE_KEYS = {
    "image",
    "images",
    "bbox",
    "bboxes",
    "derived_elements",
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


class _MarkdownImageRef(TypedDict):
    alt: str
    src: str


def _normalize_string(value: Any) -> str | None:
    return value.strip().lower() if isinstance(value, str) else None


def _get_metadata(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        meta = item.get("metadata")
    else:
        meta = getattr(item, "metadata", None)
    return dict(meta) if isinstance(meta, Mapping) else {}


def _get_text(item: Any) -> str:
    if isinstance(item, Mapping):
        return item["page_content"].strip()
    return item.page_content


def _clean_element_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return _POSITION_TAG_RE.sub("", text).strip()


def _coerce_bbox(value: Any) -> dict[str, int] | None:
    if isinstance(value, Mapping):
        x0 = _coerce_int(value.get("x0"))
        y0 = _coerce_int(value.get("y0"))
        x1 = _coerce_int(value.get("x1"))
        y1 = _coerce_int(value.get("y1"))
        if None not in {x0, y0, x1, y1}:
            return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        x0, y0, x1, y1 = (_coerce_int(part) for part in value)
        if None not in {x0, y0, x1, y1}:
            return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
    return None


def _coerce_position_bbox(parts: tuple[str, str, str, str]) -> dict[str, int] | None:
    left, right, top, bottom = (_coerce_float(part) for part in parts)
    if None in {left, right, top, bottom}:
        return None
    return {
        "x0": int(round(left)),
        "y0": int(round(top)),
        "x1": int(round(right)),
        "y1": int(round(bottom)),
    }


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
        return value
    for key in ("page", "page_number", "page_index"):
        value = _coerce_int(meta.get(key))
        if value is None:
            continue
        if key == "page_index":
            return value + 1
        return value
    pages = meta.get("pages")
    if isinstance(pages, list) and pages:
        first = _coerce_int(pages[0])
        if first is not None:
            return first + 1 if first == 0 else first
    return None


def _extract_pages(meta: Mapping[str, Any]) -> list[int] | None:
    raw = meta.get("pages")
    if not isinstance(raw, list):
        raw = meta.get("cross_page_merge_pages")
    if not isinstance(raw, list):
        return None
    pages: list[int] = []
    for item in raw:
        value = _coerce_int(item)
        if value is None or value <= 0:
            continue
        page = value
        if page not in pages:
            pages.append(page)
    return pages or None


def _classify_kind(meta: Mapping[str, Any], text: str) -> str:
    raw_kind = meta.get("element_kind")
    preferred = raw_kind.strip().lower() if isinstance(raw_kind, str) else None
    if preferred in _KNOWN_KINDS:
        return preferred

    for raw in (meta.get("doc_type_kwd"), meta.get("content_type")):
        value = raw.strip().lower() if isinstance(raw, str) else None
        if value in _KNOWN_KINDS:
            return value
        if value in {"text", "ocr"}:
            break

    raw_role = meta.get("chunk_role")
    chunk_role = raw_role.strip().lower() if isinstance(raw_role, str) else None
    if chunk_role in _KNOWN_KINDS:
        return chunk_role
    if chunk_role == "ocr":
        return "unknown"

    stripped = text.strip()
    if not stripped:
        return "unknown"
    if _DISPLAY_MATH_RE.match(stripped):
        return "equation"
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


def _extract_attributes(meta: Mapping[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    preferred_attrs = meta.get("element_attributes")
    if isinstance(preferred_attrs, Mapping):
        attrs.update(_json_safe(dict(preferred_attrs)))
    for key, value in meta.items():
        if key in _SKIP_ATTRIBUTE_KEYS:
            continue
        if key in {"page", "page_number", "page_index"}:
            continue
        if key in {"source_backend", "source_element_id"}:
            continue
        safe_value = _json_safe(value)
        if safe_value is not None:
            attrs[str(key)] = safe_value
    return attrs


def _infer_visual_kind(*, kind: str, text: str, attributes: Mapping[str, Any]) -> str | None:
    if kind != "image":
        return None
    raw_kind = attributes.get("visual_kind")
    existing = raw_kind.strip().lower() if isinstance(raw_kind, str) else None
    if existing:
        return existing
    hint = " ".join(
        str(part).strip().lower()
        for part in (
            text,
            attributes.get("source_content_type"),
            attributes.get("image_caption"),
            attributes.get("caption"),
            attributes.get("image_path"),
            attributes.get("image_url"),
            attributes.get("img_url"),
            attributes.get("src"),
            attributes.get("alt"),
        )
        if part is not None and str(part).strip()
    )
    if not hint:
        return None
    if any(token in hint for token in ("qrcode", "qr code", " qr ", "二维码")):
        return "qr"
    if "barcode" in hint or "bar code" in hint or "条码" in hint:
        return "barcode"
    if any(token in hint for token in ("flowchart", "diagram", "架构图", "流程图", "示意图")):
        return "diagram"
    if any(token in hint for token in ("chart", "graph", "plot", "图表", "曲线图", "柱状图")):
        return "chart"
    return None


def _prefer_image_code_text(*, kind: str, visual_kind: str | None, text: str, attributes: Mapping[str, Any]) -> str:
    if kind != "image":
        return text
    if visual_kind is None or visual_kind.strip().lower() not in {"qr", "barcode"}:
        return text
    code_text = _clean_element_text(attributes.get("image_code_text"))
    return code_text or text


def _extract_markdown_image_refs(markdown: str) -> list[_MarkdownImageRef]:
    refs: list[_MarkdownImageRef] = []
    for match in _MD_IMAGE_RE.finditer(markdown):
        refs.append({"alt": match.group(1).strip(), "src": match.group(2).strip()})
    for match in _HTML_IMAGE_RE.finditer(markdown):
        token = match.group(0)
        alt_match = _HTML_ALT_RE.search(token)
        refs.append(
            {
                "alt": str(alt_match.group(1) if alt_match else "").strip(),
                "src": match.group(1).strip(),
            }
        )
    return [ref for ref in refs if ref["src"]]


def _extract_positioned_image_blocks(markdown: str) -> list[dict[str, Any]]:
    positioned: list[dict[str, Any]] = []
    last_index = 0
    for match in _POSITION_TAG_DETAIL_RE.finditer(markdown):
        text = markdown[last_index : match.start()].strip()
        last_index = match.end()
        if not text:
            continue
        if not (_MD_IMAGE_RE.search(text) or _HTML_IMAGE_RE.search(text)):
            continue
        page = _coerce_int(match.group(1))
        bbox = _coerce_position_bbox((match.group(2), match.group(3), match.group(4), match.group(5)))
        positioned.append({"page": page, "bbox": bbox, "text": _clean_element_text(text)})
    return positioned


def _normalize_markdown_image_elements(
    *,
    text: str,
    tagged_markdown: str,
    parent_id: str,
    parent_page: int | None,
) -> list[dict[str, Any]]:
    image_refs = _extract_markdown_image_refs(text)
    positioned = _extract_positioned_image_blocks(tagged_markdown or text)
    if not image_refs and positioned:
        image_refs = [
            {
                "alt": _clean_element_text(item.get("text")) or "Image",
                "src": "layout://image",
            }
            for item in positioned
        ]
    if not image_refs:
        return []

    out: list[dict[str, Any]] = []
    for index, ref in enumerate(image_refs):
        position = positioned[index] if index < len(positioned) else {}
        attrs = {
            "src": ref["src"],
            "alt": ref["alt"],
            "source_content_type": "markdown_image",
        }
        text_value = ref["alt"] or Path(ref["src"]).name or "Image"
        visual_kind = _infer_visual_kind(kind="image", text=text_value, attributes=attrs)
        if visual_kind:
            attrs["visual_kind"] = visual_kind
        out.append(
            {
                "id": f"{parent_id}:image:{index}",
                "kind": "image",
                "page": position.get("page") or parent_page,
                "pages": None,
                "visual_kind": visual_kind,
                "text": text_value,
                "bbox": position.get("bbox"),
                "confidence": None,
                "source_backend": None,
                "source_element_id": None,
                "attributes": attrs,
            }
        )
    return out


def _extract_derived_attributes(meta: Mapping[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    preferred_attrs = meta.get("attributes")
    if isinstance(preferred_attrs, Mapping):
        attrs.update(_json_safe(dict(preferred_attrs)))
    for key, value in meta.items():
        if key in {
            "id",
            "kind",
            "text",
            "page",
            "pages",
            "bbox",
            "confidence",
            "attributes",
            "element_id",
            "element_kind",
            "element_text",
            "element_page",
            "element_bbox",
            "element_confidence",
            "source_backend",
            "source_element_id",
        }:
            continue
        safe_value = _json_safe(value)
        if safe_value is not None:
            attrs[str(key)] = safe_value
    return attrs


def _resolve_source_fields(
    raw: Mapping[str, Any],
    *,
    attributes: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    source_backend = raw.get("source_backend")
    if source_backend is None:
        source_backend = attributes.get("source_backend")
    source_element_id = raw.get("source_element_id")
    if source_element_id is None:
        source_element_id = attributes.get("source_element_id")
    return source_backend, source_element_id


def _resolve_element_visuals(
    raw: Mapping[str, Any],
    *,
    kind: str,
    text: str,
    attributes: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any], str]:
    visual_kind = _normalize_string(raw.get("visual_kind")) or _infer_visual_kind(
        kind=kind,
        text=text,
        attributes=attributes,
    )
    next_attributes = dict(attributes)
    if visual_kind:
        next_attributes["visual_kind"] = visual_kind
    preferred_text = _prefer_image_code_text(kind=kind, visual_kind=visual_kind, text=text, attributes=next_attributes)
    return visual_kind, next_attributes, preferred_text


def _coerce_element_confidence(raw: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        confidence = _coerce_float(raw.get(key))
        if confidence is not None:
            return confidence
    return None


def _normalize_single_derived_element(
    raw: Mapping[str, Any],
    *,
    index: int,
    parent_id: str,
    parent_page: int | None,
) -> dict[str, Any]:
    text = _clean_element_text(raw.get("text") or raw.get("element_text"))
    kind = str(raw.get("kind") or raw.get("element_kind") or "").strip().lower()
    if kind not in _KNOWN_KINDS:
        kind = _classify_kind(raw, text)
    page = _coerce_int(raw.get("page"))
    if page is None:
        page = _extract_page(raw)
    if page is None:
        page = parent_page
    pages = _extract_pages(raw)
    bbox = _coerce_bbox(raw.get("bbox"))
    if bbox is None:
        bbox = _extract_bbox(raw)
    attributes = _extract_derived_attributes(raw)
    source_backend, source_element_id = _resolve_source_fields(raw, attributes=attributes)
    visual_kind, attributes, text = _resolve_element_visuals(raw, kind=kind, text=text, attributes=attributes)
    confidence = _coerce_element_confidence(raw, "confidence", "element_confidence", "score", "seal_score")
    item_id = str(raw.get("id") or raw.get("element_id") or "").strip()
    if not item_id:
        item_id = f"{parent_id}:derived:{index}"
    return {
        "id": item_id,
        "kind": kind,
        "page": page,
        "pages": pages,
        "visual_kind": visual_kind,
        "text": text,
        "bbox": bbox,
        "confidence": confidence,
        "source_backend": source_backend,
        "source_element_id": source_element_id,
        "attributes": attributes,
    }


def _normalize_derived_elements(
    meta: Mapping[str, Any],
    *,
    parent_id: str,
    parent_page: int | None,
) -> list[dict[str, Any]]:
    raw_elements = meta.get("derived_elements")
    if not isinstance(raw_elements, list):
        return []

    out: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_elements):
        if not isinstance(raw, Mapping):
            continue
        out.append(_normalize_single_derived_element(raw, index=index, parent_id=parent_id, parent_page=parent_page))
    return out


def normalize_document_elements(items: Iterable[Document | Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items or []):
        meta = _get_metadata(item)
        text = _clean_element_text(meta.get("element_text")) or _get_text(item)
        kind = _classify_kind(meta, text)
        page = _extract_page(meta)
        pages = _extract_pages(meta)
        bbox = _extract_bbox(meta)
        attributes = _extract_attributes(meta)
        source_backend, source_element_id = _resolve_source_fields(meta, attributes=attributes)
        visual_kind = _infer_visual_kind(kind=kind, text=text, attributes=attributes)
        if visual_kind:
            attrs = dict(attributes)
            attrs["visual_kind"] = visual_kind
            attributes = attrs
        text = _prefer_image_code_text(kind=kind, visual_kind=visual_kind, text=text, attributes=attributes)
        confidence = _coerce_element_confidence(meta, "element_confidence", "seal_score", "confidence", "score")

        item_id = str(meta.get("element_id") or meta.get("id") or "").strip()
        if not item_id:
            page_part = str(page) if page is not None else "na"
            item_id = f"{kind}:{page_part}:{index}"

        out.append(
            {
                "id": item_id,
                "kind": kind,
                "page": page,
                "pages": pages,
                "visual_kind": visual_kind,
                "text": text,
                "bbox": bbox,
                "confidence": confidence,
                "source_backend": source_backend,
                "source_element_id": source_element_id,
                "attributes": attributes,
            }
        )
        tagged_markdown = str(meta.get("position_tagged_markdown") or "")
        has_derived_elements = isinstance(meta.get("derived_elements"), list) and bool(meta.get("derived_elements"))
        if kind != "image" and not has_derived_elements:
            out.extend(
                _normalize_markdown_image_elements(
                    text=text,
                    tagged_markdown=tagged_markdown,
                    parent_id=item_id,
                    parent_page=page,
                )
            )
        out.extend(_normalize_derived_elements(meta, parent_id=item_id, parent_page=page))
    return out


__all__ = ["normalize_document_elements"]
