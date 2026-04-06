from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        if out != out:
            return None
        return float(out)
    except Exception:
        return None


def _as_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _iter_layout_names(zf: zipfile.ZipFile) -> list[str]:
    candidates: list[str] = []
    for name in zf.namelist():
        lowered = name.lower()
        if lowered.endswith("layout.json"):
            candidates.append(name)

    def sort_key(name: str) -> tuple[int, int, str]:
        lowered = name.lower()
        exact = 0 if lowered == "layout.json" or lowered.endswith("/layout.json") else 1
        depth = len([part for part in name.replace("\\", "/").split("/") if part])
        return (exact, depth, lowered)

    return sorted(candidates, key=sort_key)


def _load_page_sizes(zf: zipfile.ZipFile) -> dict[int, tuple[float, float]]:
    for name in _iter_layout_names(zf):
        try:
            payload = json.loads(zf.read(name).decode("utf-8", errors="ignore"))
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        pdf_info = payload.get("pdf_info")
        if not isinstance(pdf_info, list):
            continue

        page_sizes: dict[int, tuple[float, float]] = {}
        for page in pdf_info:
            if not isinstance(page, dict):
                continue

            page_idx = _as_int(page.get("page_idx"))
            raw_page_size = page.get("page_size")
            if page_idx is None or not isinstance(raw_page_size, (list, tuple)) or len(raw_page_size) != 2:
                continue

            page_width = _as_float(raw_page_size[0])
            page_height = _as_float(raw_page_size[1])
            if page_width is None or page_height is None or page_width <= 0 or page_height <= 0:
                continue

            page_sizes[page_idx] = (page_width, page_height)

        if page_sizes:
            return page_sizes

    return {}


def _collect_normalized_pages(
    items: list[dict[str, Any]], page_sizes: dict[int, tuple[float, float]]
) -> set[int]:
    needs_normalization: set[int] = set()
    if not items or not page_sizes:
        return needs_normalization

    max_coords_by_page: dict[int, tuple[float, float]] = {}
    for item in items:
        page_idx = _as_int(item.get("page_idx"))
        bbox = item.get("bbox")
        if page_idx is None or page_idx not in page_sizes:
            continue
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue

        right = _as_float(bbox[2])
        bottom = _as_float(bbox[3])
        if right is None or bottom is None:
            continue

        prev_right, prev_bottom = max_coords_by_page.get(page_idx, (0.0, 0.0))
        max_coords_by_page[page_idx] = (max(prev_right, right), max(prev_bottom, bottom))

    for page_idx, (max_right, max_bottom) in max_coords_by_page.items():
        page_width, page_height = page_sizes[page_idx]
        if max_right > page_width + 1.0 or max_bottom > page_height + 1.0:
            needs_normalization.add(page_idx)

    return needs_normalization


def _build_position_tag(
    item: dict[str, Any],
    *,
    page_sizes: dict[int, tuple[float, float]],
    normalized_pages: set[int],
) -> str:
    page_idx = _as_int(item.get("page_idx"))
    bbox = item.get("bbox")
    if page_idx is None or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return ""

    left = _as_float(bbox[0])
    top = _as_float(bbox[1])
    right = _as_float(bbox[2])
    bottom = _as_float(bbox[3])
    if None in {left, top, right, bottom}:
        return ""

    if page_idx in normalized_pages:
        page_width, page_height = page_sizes.get(page_idx, (0.0, 0.0))
        if page_width > 0 and page_height > 0:
            left = (left / 1000.0) * page_width
            right = (right / 1000.0) * page_width
            top = (top / 1000.0) * page_height
            bottom = (bottom / 1000.0) * page_height

    return f"@@{int(page_idx) + 1}\t{float(left):.1f}\t{float(right):.1f}\t{float(top):.1f}\t{float(bottom):.1f}##"


def _extract_block_text(item: dict[str, Any]) -> str:
    text = str(item.get("text") or "").strip()
    if text:
        return text

    item_type = str(item.get("type") or "").strip().lower()
    if item_type == "table":
        parts = _as_lines(item.get("table_caption"))
        body = str(item.get("table_body") or "").strip()
        if body:
            parts.append(body)
        parts.extend(_as_lines(item.get("table_footnote")))
        return "\n".join(parts).strip()

    if item_type == "image":
        parts = _as_lines(item.get("image_caption"))
        parts.extend(_as_lines(item.get("image_footnote")))
        joined = "\n".join(parts).strip()
        return joined or "![Image](layout://image)"

    if item_type == "list":
        return "\n".join(_as_lines(item.get("list_items"))).strip()

    if item_type == "code":
        parts = _as_lines(item.get("code_caption"))
        body = str(item.get("code_body") or "").strip()
        if body:
            parts.insert(0, body)
        return "\n".join(parts).strip()

    return ""


def _iter_content_list_names(zf: zipfile.ZipFile) -> list[str]:
    candidates: list[str] = []
    for name in zf.namelist():
        lowered = name.lower()
        if lowered.endswith(".json") and "content_list" in lowered:
            candidates.append(name)

    def sort_key(name: str) -> tuple[int, int, str]:
        lowered = name.lower()
        exact = 0 if lowered.endswith("_content_list.json") else 1
        depth = len([part for part in name.replace("\\", "/").split("/") if part])
        return (exact, depth, lowered)

    return sorted(candidates, key=sort_key)


def _load_content_list(zf: zipfile.ZipFile) -> list[dict[str, Any]]:
    for name in _iter_content_list_names(zf):
        try:
            payload = json.loads(zf.read(name).decode("utf-8", errors="ignore"))
        except Exception:
            continue

        if not isinstance(payload, list):
            continue

        items = [item for item in payload if isinstance(item, dict)]
        if items and any(isinstance(item.get("bbox"), (list, tuple)) for item in items):
            return items

    return []


def _build_position_tagged_markdown(
    items: list[dict[str, Any]], *, page_sizes: dict[int, tuple[float, float]] | None = None
) -> str:
    blocks: list[str] = []
    resolved_page_sizes = page_sizes or {}
    normalized_pages = _collect_normalized_pages(items, resolved_page_sizes)

    for item in items:
        tag = _build_position_tag(
            item,
            page_sizes=resolved_page_sizes,
            normalized_pages=normalized_pages,
        )
        if not tag:
            continue

        text = _extract_block_text(item)
        blocks.append(f"{text}{tag}" if text else tag)

    return "\n\n".join(blocks).strip()


def extract_position_tagged_markdown_from_zip_bytes(zip_bytes: bytes) -> str:
    if not zip_bytes:
        return ""

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            items = _load_content_list(zf)
            page_sizes = _load_page_sizes(zf)
            return _build_position_tagged_markdown(items, page_sizes=page_sizes)
    except Exception:
        return ""


def extract_position_tagged_markdown_from_zip_path(zip_path: str | Path) -> str:
    try:
        with zipfile.ZipFile(Path(zip_path), "r") as zf:
            items = _load_content_list(zf)
            page_sizes = _load_page_sizes(zf)
            return _build_position_tagged_markdown(items, page_sizes=page_sizes)
    except Exception:
        return ""


__all__ = [
    "extract_position_tagged_markdown_from_zip_bytes",
    "extract_position_tagged_markdown_from_zip_path",
]
