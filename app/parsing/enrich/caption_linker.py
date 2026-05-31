from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_FIGURE_CAPTION_RE = re.compile(r"^\s*(图|figure|fig\.)\s*[\d一二三四五六七八九十]+", re.IGNORECASE)
_TABLE_CAPTION_RE = re.compile(r"^\s*(表|table)\s*[\d一二三四五六七八九十]+", re.IGNORECASE)


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    x0 = _coerce_int(value.get("x0"))
    y0 = _coerce_int(value.get("y0"))
    x1 = _coerce_int(value.get("x1"))
    y1 = _coerce_int(value.get("y1"))
    if None in {x0, y0, x1, y1}:
        return None
    return {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}


def _caption_pattern(media_kind: str) -> re.Pattern[str]:
    return _TABLE_CAPTION_RE if str(media_kind or "").strip().lower() == "table" else _FIGURE_CAPTION_RE


def _vertical_gap(a: Mapping[str, int], b: Mapping[str, int]) -> int:
    if int(a["y1"]) <= int(b["y0"]):
        return int(b["y0"]) - int(a["y1"])
    if int(b["y1"]) <= int(a["y0"]):
        return int(a["y0"]) - int(b["y1"])
    return 0


def _horizontal_overlap(a: Mapping[str, int], b: Mapping[str, int]) -> int:
    return max(0, min(int(a["x1"]), int(b["x1"])) - max(int(a["x0"]), int(b["x0"])))


def find_nearest_caption(
    elements: Sequence[Mapping[str, Any]] | None,
    *,
    media_kind: str,
    page: int | None,
    bbox: Mapping[str, Any] | None,
    max_vertical_gap: int = 160,
) -> dict[str, Any] | None:
    media_bbox = _bbox(bbox)
    if page is None or media_bbox is None:
        return None
    pattern = _caption_pattern(media_kind)
    candidates: list[tuple[int, int, Mapping[str, Any]]] = []
    for raw in elements or []:
        if not isinstance(raw, Mapping):
            continue
        if _coerce_int(raw.get("page")) != int(page):
            continue
        text = str(raw.get("text") or "").strip()
        if not pattern.match(text):
            continue
        candidate_bbox = _bbox(raw.get("bbox"))
        if candidate_bbox is None:
            continue
        gap = _vertical_gap(candidate_bbox, media_bbox)
        if gap > int(max_vertical_gap):
            continue
        overlap = _horizontal_overlap(candidate_bbox, media_bbox)
        candidates.append((gap, -overlap, raw))
    if not candidates:
        return None
    _gap, _overlap, selected = min(candidates, key=lambda item: (item[0], item[1]))
    return {
        "id": str(selected.get("id") or ""),
        "text": str(selected.get("text") or "").strip(),
        "page": int(page),
        "bbox": dict(_bbox(selected.get("bbox")) or {}),
        "source_element_id": selected.get("source_element_id"),
    }


__all__ = ["find_nearest_caption"]
