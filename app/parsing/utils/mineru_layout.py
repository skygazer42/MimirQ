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


def _build_position_tag(item: dict[str, Any]) -> str:
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
        if items and any(_build_position_tag(item) for item in items):
            return items

    return []


def _build_position_tagged_markdown(items: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in items:
        tag = _build_position_tag(item)
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
            return _build_position_tagged_markdown(_load_content_list(zf))
    except Exception:
        return ""


def extract_position_tagged_markdown_from_zip_path(zip_path: str | Path) -> str:
    try:
        with zipfile.ZipFile(Path(zip_path), "r") as zf:
            return _build_position_tagged_markdown(_load_content_list(zf))
    except Exception:
        return ""


__all__ = [
    "extract_position_tagged_markdown_from_zip_bytes",
    "extract_position_tagged_markdown_from_zip_path",
]
