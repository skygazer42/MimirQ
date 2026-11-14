import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.parsing.utils.block_schema import block_bbox_value, block_page, block_text

_DIGIT_RE = re.compile(r"\d+")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class HeaderFooterRemovalResult:
    elements: list[dict[str, Any]]
    changed: bool
    removed_count: int
    removed_ids: list[str]
    pages: list[int]
    method: str = "edge_repeat"
    warnings: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema": "mimirq.header_footer_removal.v1",
            "method": self.method,
            "changed": bool(self.changed),
            "removed_count": int(self.removed_count),
            "removed_ids": list(self.removed_ids),
            "pages": list(self.pages),
            "warnings": list(self.warnings),
        }


def _normalize_repeated_text(text: str) -> str:
    normalized = _SPACE_RE.sub(" ", text.strip().lower())
    normalized = _DIGIT_RE.sub("#", normalized)
    return normalized.strip()


def _normalize_elements(elements: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    valid: list[dict[str, Any]] = []
    missing_geometry = False
    for index, raw in enumerate(elements):
        element = dict(raw)
        page = block_page(element)
        x0 = block_bbox_value(element, "x0")
        x1 = block_bbox_value(element, "x1")
        y0 = block_bbox_value(element, "y0")
        y1 = block_bbox_value(element, "y1")
        text = block_text(element)
        if page is None or x0 is None or x1 is None or y0 is None or y1 is None or not text:
            missing_geometry = True
            continue
        valid.append(
            {
                "index": index,
                "page": page,
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "text": text,
                "element": element,
            }
        )
    return valid, missing_geometry


def _page_bounds(valid: Sequence[dict[str, Any]]) -> dict[int, tuple[float, float]]:
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in valid:
        by_page[item["page"]].append(item)
    bounds: dict[int, tuple[float, float]] = {}
    for page, items in by_page.items():
        top = min(item["y0"] for item in items)
        bottom = max(item["y1"] for item in items)
        bounds[page] = (top, bottom)
    return bounds


def _edge_zone(item: Mapping[str, Any], bounds: Mapping[int, tuple[float, float]], *, band_ratio: float) -> str | None:
    page_top, page_bottom = bounds[item["page"]]
    height = max(1.0, page_bottom - page_top)
    band = max(8.0, height * max(0.01, float(band_ratio)))
    y0 = item["y0"]
    y1 = item["y1"]
    if y1 <= page_top + band:
        return "header"
    if y0 >= page_bottom - band:
        return "footer"
    return None


def remove_repeated_header_footer_elements(
    elements: Sequence[Mapping[str, Any]] | None,
    *,
    min_pages: int = 2,
    min_repetition_ratio: float = 0.6,
    band_ratio: float = 0.12,
) -> HeaderFooterRemovalResult:
    original = [dict(item) for item in (elements or []) if isinstance(item, Mapping)]
    if not original:
        return HeaderFooterRemovalResult(elements=[], changed=False, removed_count=0, removed_ids=[], pages=[])

    valid, missing_geometry = _normalize_elements(original)
    bounds = _page_bounds(valid)
    pages = sorted(bounds)
    if len(pages) < int(min_pages):
        return HeaderFooterRemovalResult(
            elements=original,
            changed=False,
            removed_count=0,
            removed_ids=[],
            pages=pages,
            warnings=["insufficient_pages"],
        )

    threshold = max(int(min_pages), int(math.ceil(len(pages) * max(0.0, min(1.0, float(min_repetition_ratio))))))
    candidates: list[dict[str, Any]] = []
    seen_pages_by_key: dict[tuple[str, str], set[int]] = defaultdict(set)
    for item in valid:
        zone = _edge_zone(item, bounds, band_ratio=band_ratio)
        if zone is None:
            continue
        key_text = _normalize_repeated_text(item["text"])
        key = (zone, key_text)
        candidates.append({"key": key, "item": item})
        seen_pages_by_key[key].add(item["page"])

    repeated_keys = {key for key, key_pages in seen_pages_by_key.items() if len(key_pages) >= threshold}
    remove_indexes = {candidate["item"]["index"] for candidate in candidates if candidate["key"] in repeated_keys}
    if not remove_indexes:
        return HeaderFooterRemovalResult(
            elements=original,
            changed=False,
            removed_count=0,
            removed_ids=[],
            pages=pages,
            warnings=["missing_geometry"] if missing_geometry else [],
        )

    kept: list[dict[str, Any]] = []
    removed_ids: list[str] = []
    for index, element in enumerate(original):
        if index in remove_indexes:
            removed_ids.append(str(element.get("id") or index))
            continue
        kept.append(dict(element))
    return HeaderFooterRemovalResult(
        elements=kept,
        changed=True,
        removed_count=len(remove_indexes),
        removed_ids=removed_ids,
        pages=pages,
        warnings=["missing_geometry"] if missing_geometry else [],
    )


__all__ = ["HeaderFooterRemovalResult", "remove_repeated_header_footer_elements"]
