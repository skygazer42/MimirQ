
import re
from typing import Any

from sqlalchemy.orm.attributes import set_committed_value

MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]*\)")
HTML_TABLE_RE = re.compile(r"<table\b", re.IGNORECASE)


def _safe_int(value: Any) -> int:
    try:
        numeric = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, numeric)


def _element_texts(metadata: dict[str, Any]) -> list[str]:
    elements = metadata.get("elements")
    if not isinstance(elements, list):
        return []

    texts: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        text = element.get("text") or element.get("content") or element.get("markdown")
        if isinstance(text, str) and text:
            texts.append(text)
    return texts


def _count_element_images(metadata: dict[str, Any]) -> int:
    count = 0
    elements = metadata.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            kind = str(
                element.get("kind")
                or element.get("type")
                or element.get("category")
                or element.get("visual_kind")
                or ""
            ).lower()
            if kind in {"image", "figure", "picture"}:
                count += 1

    for text in _element_texts(metadata):
        count += len(MARKDOWN_IMAGE_RE.findall(text))
    return count


def _count_element_tables(metadata: dict[str, Any]) -> int:
    count = 0
    elements = metadata.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            kind = str(
                element.get("kind")
                or element.get("type")
                or element.get("category")
                or ""
            ).lower()
            if kind == "table":
                count += 1

    for text in _element_texts(metadata):
        count += len(HTML_TABLE_RE.findall(text))
    return count


def build_runtime_document_metadata(document: Any) -> dict[str, Any]:
    """
    Enrich transient API metadata using facts already stored on the document row.

    This intentionally does not write back to the database. It makes list/detail
    responses useful without opening source files on the request path.
    """

    raw_metadata = getattr(document, "doc_metadata", None)
    metadata: dict[str, Any] = dict(raw_metadata or {}) if isinstance(raw_metadata, dict) else {}

    if _safe_int(metadata.get("image_count")) <= 0:
        image_count = _count_element_images(metadata)
        if image_count > 0:
            metadata["image_count"] = image_count
            metadata["image_count_source"] = "elements"

    if _safe_int(metadata.get("table_count")) <= 0:
        table_count = _count_element_tables(metadata)
        if table_count > 0:
            metadata["table_count"] = table_count
            metadata["table_count_source"] = "elements"

    if _safe_int(metadata.get("block_count")) <= 0:
        elements = metadata.get("elements")
        if isinstance(elements, list) and elements:
            metadata["block_count"] = len(elements)
            metadata["block_count_source"] = "elements"

    return metadata


def attach_runtime_document_metadata(document: Any) -> None:
    metadata = build_runtime_document_metadata(document)
    set_committed_value(document, "doc_metadata", metadata)
