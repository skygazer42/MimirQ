from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

POSITION_TAG_RE = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value):
            return 0
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0
        try:
            return int(float(s))
        except Exception:
            return 0
    try:
        return int(value)
    except Exception:
        return 0


def count_position_tag_blocks(markdown: str) -> int:
    """
    Count "position blocks" in markdown.

    A position block is a chunk of text associated with 1+ position tags (e.g. @@page...##),
    matching the workspace UI's block extraction semantics (only blocks that have positions).
    """
    if not markdown:
        return 0

    block_count = 0
    last_index = 0
    has_last_block = False

    for match in POSITION_TAG_RE.finditer(markdown):
        text_chunk = markdown[last_index : match.start()]
        text = text_chunk.strip()
        if text or not has_last_block:
            block_count += 1
            has_last_block = True

        last_index = match.end()

    return int(block_count)


def _iter_metadata(documents: Iterable[Any] | None) -> Iterable[Mapping[str, Any]]:
    for item in documents or []:
        meta: Any = None
        if isinstance(item, Mapping):
            meta = item.get("metadata")
        else:
            meta = getattr(item, "metadata", None)
        if isinstance(meta, Mapping):
            yield meta
        else:
            yield {}


def compute_parsing_artifact_stats(
    *,
    documents: Iterable[Any] | None,
    original_markdown: str,
    pdf_quality: Mapping[str, Any] | None,
) -> dict[str, int]:
    table_count = 0
    image_count = 0

    for meta in _iter_metadata(documents):
        content_type = str(meta.get("content_type") or "").strip().lower()
        doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
        if content_type == "table" or doc_type == "table":
            table_count += 1
        if content_type == "image" or doc_type == "image":
            image_count += 1

    page_count = 0
    if isinstance(pdf_quality, Mapping):
        page_count = max(0, _coerce_int(pdf_quality.get("page_count")))

    block_count = count_position_tag_blocks(original_markdown or "")

    return {
        "page_count": int(page_count),
        "table_count": int(table_count),
        "image_count": int(image_count),
        "block_count": int(block_count),
    }
