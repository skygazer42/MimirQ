from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        out = float(value)
        if out != out:
            return None
        return out
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _item_meta(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        meta = item.get("metadata")
        if isinstance(meta, Mapping):
            return meta
        return item
    meta = getattr(item, "metadata", None)
    if isinstance(meta, Mapping):
        return meta
    return {}


def _normalize_items(items: Sequence[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(items or []):
        meta = _item_meta(item)
        page = _coerce_int(meta.get("page"))
        if page is None:
            page = _coerce_int(meta.get("page_number"))
        x0 = _coerce_float(meta.get("x0"))
        if x0 is None:
            x0 = _coerce_float(meta.get("left"))
        y0 = _coerce_float(meta.get("y0"))
        if y0 is None:
            y0 = _coerce_float(meta.get("top"))
        x1 = _coerce_float(meta.get("x1"))
        if x1 is None and x0 is not None:
            width = _coerce_float(meta.get("width"))
            x1 = x0 + width if width is not None else None
        y1 = _coerce_float(meta.get("y1"))
        if y1 is None and y0 is not None:
            height = _coerce_float(meta.get("height"))
            y1 = y0 + height if height is not None else None
        if page is None or x0 is None or y0 is None or x1 is None or y1 is None:
            continue
        out.append(
            {
                "obs_index": idx,
                "page": int(page),
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
            }
        )
    return out


def _column_threshold(page_items: Sequence[dict[str, Any]]) -> float | None:
    centers = sorted((item["x0"] + item["x1"]) / 2.0 for item in page_items)
    if len(centers) < 4:
        return None
    page_min = min(item["x0"] for item in page_items)
    page_max = max(item["x1"] for item in page_items)
    page_width = max(1.0, page_max - page_min)

    best_gap = 0.0
    threshold = None
    for left, right in zip(centers, centers[1:], strict=False):
        gap = right - left
        if gap > best_gap:
            best_gap = gap
            threshold = (left + right) / 2.0

    if threshold is None or best_gap < page_width * 0.18:
        return None
    return threshold


def _expected_order_for_page(page_items: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    threshold = _column_threshold(page_items)
    if threshold is None:
        return sorted(page_items, key=lambda item: (item["y0"], item["x0"], item["obs_index"])), False

    return (
        sorted(
            page_items,
            key=lambda item: (
                0 if ((item["x0"] + item["x1"]) / 2.0) <= threshold else 1,
                item["y0"],
                item["x0"],
                item["obs_index"],
            ),
        ),
        True,
    )


def score_reading_order(items: Sequence[Any] | None) -> dict[str, Any]:
    normalized = _normalize_items(items)
    if not normalized:
        return {
            "score": 1.0,
            "items": 0,
            "pages": 0,
            "multi_column_pages": 0,
            "inversions": 0,
        }

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in normalized:
        by_page[item["page"]].append(item)

    inversions = 0
    total_pairs = 0
    multi_column_pages = 0

    for page_items in by_page.values():
        expected, is_multi_column = _expected_order_for_page(page_items)
        if is_multi_column:
            multi_column_pages += 1
        expected_rank = {item["obs_index"]: idx for idx, item in enumerate(expected)}
        observed = sorted(page_items, key=lambda item: item["obs_index"])
        n = len(observed)
        total_pairs += max(0, n * (n - 1) // 2)
        for idx, left in enumerate(observed):
            for right in observed[idx + 1 :]:
                if expected_rank[left["obs_index"]] > expected_rank[right["obs_index"]]:
                    inversions += 1

    score = 1.0 if total_pairs <= 0 else max(0.0, 1.0 - (float(inversions) / float(total_pairs)))
    return {
        "score": round(score, 3),
        "items": int(len(normalized)),
        "pages": int(len(by_page)),
        "multi_column_pages": int(multi_column_pages),
        "inversions": int(inversions),
    }


def score_pdfplumber_reading_order(pages: Iterable[Any] | None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages or [], start=1):
        try:
            words = page.extract_words() or []
        except Exception:
            words = []
        for word in words:
            if not isinstance(word, Mapping):
                continue
            items.append(
                {
                    "page": page_index,
                    "x0": word.get("x0"),
                    "y0": word.get("top"),
                    "x1": word.get("x1"),
                    "y1": word.get("bottom"),
                }
            )
    return score_reading_order(items)


__all__ = ["score_pdfplumber_reading_order", "score_reading_order"]
