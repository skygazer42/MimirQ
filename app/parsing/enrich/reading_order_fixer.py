
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ReadingOrderFixResult:
    elements: list[dict[str, Any]]
    changed: bool
    items: int
    pages: list[int]
    column_pages: int
    method: str = "geometry_columns"
    warnings: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema": "mimirq.reading_order_fix.v1",
            "method": self.method,
            "changed": bool(self.changed),
            "items": int(self.items),
            "pages": list(self.pages),
            "column_pages": int(self.column_pages),
            "warnings": list(self.warnings),
        }


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        if out != out:
            return None
        return out
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _bbox_value(element: Mapping[str, Any], key: str) -> float | None:
    bbox = element.get("bbox")
    if isinstance(bbox, Mapping):
        return _coerce_float(bbox.get(key))
    return None


def _page_value(element: Mapping[str, Any]) -> int | None:
    page = _coerce_int(element.get("page"))
    if page is not None and page > 0:
        return int(page)
    pages = element.get("pages")
    if isinstance(pages, list) and pages:
        first = _coerce_int(pages[0])
        if first is not None and first > 0:
            return int(first)
    return None


def _normalize_elements(elements: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, raw in enumerate(elements):
        element = dict(raw)
        page = _page_value(element)
        x0 = _bbox_value(element, "x0")
        x1 = _bbox_value(element, "x1")
        y0 = _bbox_value(element, "y0")
        y1 = _bbox_value(element, "y1")
        if page is None or x0 is None or x1 is None or y0 is None or y1 is None:
            invalid.append({"index": index, "element": element})
            continue
        valid.append(
            {
                "index": index,
                "page": int(page),
                "x0": float(x0),
                "x1": float(x1),
                "y0": float(y0),
                "y1": float(y1),
                "element": element,
            }
        )
    return valid, invalid


def _column_thresholds(items: Sequence[dict[str, Any]], *, min_items: int) -> list[float]:
    if len(items) < int(min_items):
        return []
    centers = sorted((float(item["x0"]) + float(item["x1"])) / 2.0 for item in items)
    page_min = min(float(item["x0"]) for item in items)
    page_max = max(float(item["x1"]) for item in items)
    width = max(1.0, page_max - page_min)

    thresholds: list[float] = []
    for left, right in zip(centers, centers[1:], strict=False):
        gap = float(right) - float(left)
        if gap >= width * 0.18:
            threshold = (float(left) + float(right)) / 2.0
            if not thresholds or abs(threshold - thresholds[-1]) > width * 0.06:
                thresholds.append(float(threshold))
    return thresholds[:4]


def _sort_page_items(items: Sequence[dict[str, Any]], *, min_column_items: int) -> tuple[list[dict[str, Any]], bool]:
    thresholds = _column_thresholds(items, min_items=min_column_items)
    if not thresholds:
        return sorted(items, key=lambda item: int(item["index"])), False

    page_min = min(float(item["x0"]) for item in items)
    page_max = max(float(item["x1"]) for item in items)
    page_top = min(float(item["y0"]) for item in items)
    page_bottom = max(float(item["y1"]) for item in items)
    width = max(1.0, page_max - page_min)
    height = max(1.0, page_bottom - page_top)

    def flow_group(item: dict[str, Any]) -> int:
        span = max(0.0, float(item["x1"]) - float(item["x0"])) / width
        if span >= 0.75:
            if float(item["y0"]) <= page_top + height * 0.12:
                return -1
            return len(thresholds) + 1
        center = (float(item["x0"]) + float(item["x1"])) / 2.0
        for idx, threshold in enumerate(thresholds):
            if center <= threshold:
                return idx
        return len(thresholds)

    return (
        sorted(
            items,
            key=lambda item: (
                flow_group(item),
                float(item["y0"]),
                float(item["x0"]),
                int(item["index"]),
            ),
        ),
        True,
    )


def fix_reading_order_elements(
    elements: Sequence[Mapping[str, Any]] | None,
    *,
    min_column_items: int = 4,
) -> ReadingOrderFixResult:
    original = [dict(item) for item in (elements or []) if isinstance(item, Mapping)]
    if not original:
        return ReadingOrderFixResult(elements=[], changed=False, items=0, pages=[], column_pages=0)

    valid, invalid = _normalize_elements(original)
    if not valid:
        return ReadingOrderFixResult(
            elements=original,
            changed=False,
            items=0,
            pages=[],
            column_pages=0,
            warnings=["missing_geometry"],
        )

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in valid:
        by_page[int(item["page"])].append(item)

    sorted_items: list[dict[str, Any]] = []
    column_pages = 0
    for page in sorted(by_page):
        page_items, is_column_page = _sort_page_items(by_page[page], min_column_items=min_column_items)
        if is_column_page:
            column_pages += 1
        sorted_items.extend(page_items)
    if column_pages <= 0:
        return ReadingOrderFixResult(
            elements=original,
            changed=False,
            items=int(len(valid)),
            pages=[int(page) for page in sorted(by_page)],
            column_pages=0,
            warnings=["missing_geometry"] if invalid else [],
        )

    invalid_sorted = sorted(invalid, key=lambda item: int(item["index"]))
    fixed = [dict(item["element"]) for item in sorted_items] + [dict(item["element"]) for item in invalid_sorted]
    original_ids = [str(item.get("id") or index) for index, item in enumerate(original)]
    fixed_ids = [str(item.get("id") or index) for index, item in enumerate(fixed)]
    changed = original_ids != fixed_ids
    pages = sorted(by_page)
    warnings = ["missing_geometry"] if invalid else []
    return ReadingOrderFixResult(
        elements=fixed,
        changed=bool(changed),
        items=int(len(valid)),
        pages=[int(page) for page in pages],
        column_pages=int(column_pages),
        warnings=warnings,
    )


__all__ = ["ReadingOrderFixResult", "fix_reading_order_elements"]
