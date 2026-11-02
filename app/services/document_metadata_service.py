import re
from typing import Any

from sqlalchemy.orm.attributes import set_committed_value

from app.models.document import Document as DBDocument

MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]*\)")
HTML_TABLE_RE = re.compile(r"<table\b", re.IGNORECASE)


def apply_user_metadata_patch(*, current: dict[str, Any], patch: dict[str, Any], replace: bool) -> dict[str, Any]:
    next_user = _merge_user_metadata_patch(current=current, patch=patch, replace=replace)
    _normalize_user_metadata_tags(next_user, replace=replace)
    _normalize_user_metadata_notes(next_user)
    return next_user


def attach_runtime_document_metadata(document: DBDocument) -> None:
    metadata = build_runtime_document_metadata(document)
    set_committed_value(document, "doc_metadata", metadata)


def build_runtime_document_metadata(document: DBDocument) -> dict[str, Any]:
    """
    Enrich transient API metadata using facts already stored on the document row.

    This intentionally does not write back to the database. It makes list/detail
    responses useful without opening source files on the request path.
    """

    raw_metadata = document.doc_metadata
    metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}

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


def _merge_user_metadata_patch(*, current: dict[str, Any], patch: dict[str, Any], replace: bool) -> dict[str, Any]:
    if replace:
        return dict(patch)

    next_user = dict(current)
    for key, value in patch.items():
        if value is None:
            next_user.pop(key, None)
        else:
            next_user[key] = value
    return next_user


def _normalize_user_metadata_tags(next_user: dict[str, Any], *, replace: bool) -> None:
    tags = next_user.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    if isinstance(tags, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            if not isinstance(raw, str):
                continue
            val = raw.strip()
            if not val:
                continue
            key = val.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(val[:64])
        next_user["tags"] = cleaned[:50]
    elif tags is None and "tags" in next_user and not replace:
        next_user.pop("tags", None)


def _normalize_user_metadata_notes(next_user: dict[str, Any]) -> None:
    notes = next_user.get("notes")
    if isinstance(notes, str):
        val = notes.strip()
        if not val:
            next_user.pop("notes", None)
        else:
            next_user["notes"] = val[:20_000]


def _safe_int(value: object) -> int:
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
            kind = str(element.get("kind") or element.get("type") or element.get("category") or "").lower()
            if kind == "table":
                count += 1

    for text in _element_texts(metadata):
        count += len(HTML_TABLE_RE.findall(text))
    return count
