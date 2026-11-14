import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.parsing.utils.scalars import coerce_int as _coerce_int

_FIGURE_CAPTION_RE = re.compile(r"^\s*(图|figure|fig\.)\s*[\d一二三四五六七八九十]+", re.IGNORECASE)
_TABLE_CAPTION_RE = re.compile(r"^\s*(表|table)\s*[\d一二三四五六七八九十]+", re.IGNORECASE)


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    x0 = _coerce_int(value.get("x0"))
    y0 = _coerce_int(value.get("y0"))
    x1 = _coerce_int(value.get("x1"))
    y1 = _coerce_int(value.get("y1"))
    if x0 is None or y0 is None or x1 is None or y1 is None:
        return None
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _vertical_gap(a: Mapping[str, int], b: Mapping[str, int]) -> int:
    if a["y1"] <= b["y0"]:
        return b["y0"] - a["y1"]
    if b["y1"] <= a["y0"]:
        return a["y0"] - b["y1"]
    return 0


def _horizontal_overlap(a: Mapping[str, int], b: Mapping[str, int]) -> int:
    return max(0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))


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
    pattern = _TABLE_CAPTION_RE if media_kind.strip().lower() == "table" else _FIGURE_CAPTION_RE
    candidates: list[tuple[int, int, Mapping[str, Any], dict[str, int]]] = []
    for raw in elements or []:
        if not isinstance(raw, Mapping):
            continue
        if _coerce_int(raw.get("page")) != page:
            continue
        text = raw["text"].strip()
        if not pattern.match(text):
            continue
        candidate_bbox = _bbox(raw.get("bbox"))
        if candidate_bbox is None:
            continue
        gap = _vertical_gap(candidate_bbox, media_bbox)
        if gap > max_vertical_gap:
            continue
        overlap = _horizontal_overlap(candidate_bbox, media_bbox)
        candidates.append((gap, -overlap, raw, candidate_bbox))
    if not candidates:
        return None
    _gap, _overlap, selected, selected_bbox = min(candidates, key=lambda item: (item[0], item[1]))
    return {
        "id": selected["id"],
        "text": selected["text"].strip(),
        "page": page,
        "bbox": selected_bbox,
        "source_element_id": selected.get("source_element_id"),
    }


__all__ = ["find_nearest_caption"]
