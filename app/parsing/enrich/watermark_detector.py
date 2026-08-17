
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.parsing.enrich.document_noise_rules import classify_document_noise_text

_SPACE_RE = re.compile(r"\s+")
_COMMON_SHORT_REPEAT_TEXT = {"项目", "名称", "序号", "日期", "金额", "备注", "合计", "小计"}


@dataclass(frozen=True, slots=True)
class WatermarkRemovalResult:
    elements: list[dict[str, Any]]
    changed: bool
    removed_count: int
    removed_ids: list[str]
    pages: list[int]
    reasons: dict[str, int] = field(default_factory=dict)
    method: str = "text_watermark_noise"
    warnings: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema": "mimirq.watermark_removal.v1",
            "method": self.method,
            "changed": bool(self.changed),
            "removed_count": int(self.removed_count),
            "removed_ids": list(self.removed_ids),
            "pages": list(self.pages),
            "reasons": dict(self.reasons),
            "warnings": list(self.warnings),
        }


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


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


def _text_value(element: Mapping[str, Any]) -> str:
    return str(element.get("text") or element.get("element_text") or "").strip()


def _kind_value(element: Mapping[str, Any]) -> str:
    return str(element.get("kind") or element.get("element_kind") or "").strip().lower()


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


def _bbox_center_key(element: Mapping[str, Any]) -> tuple[int, int] | None:
    bbox = element.get("bbox")
    if not isinstance(bbox, Mapping):
        return None
    x0 = _coerce_float(bbox.get("x0"))
    x1 = _coerce_float(bbox.get("x1"))
    y0 = _coerce_float(bbox.get("y0"))
    y1 = _coerce_float(bbox.get("y1"))
    if x0 is None or x1 is None or y0 is None or y1 is None:
        return None
    # Coarse buckets make repeated overlay detection robust to minor PDF extraction drift.
    return (int(round(((x0 + x1) / 2.0) / 20.0)), int(round(((y0 + y1) / 2.0) / 20.0)))


def _page_bounds(elements: Sequence[Mapping[str, Any]]) -> dict[int, tuple[float, float]]:
    bounds: dict[int, tuple[float, float]] = {}
    for element in elements:
        page = _page_value(element)
        bbox = element.get("bbox")
        if page is None or not isinstance(bbox, Mapping):
            continue
        y0 = _coerce_float(bbox.get("y0"))
        y1 = _coerce_float(bbox.get("y1"))
        if y0 is None or y1 is None:
            continue
        if page not in bounds:
            bounds[int(page)] = (float(y0), float(y1))
            continue
        top, bottom = bounds[int(page)]
        bounds[int(page)] = (min(top, float(y0)), max(bottom, float(y1)))
    return bounds


def _is_center_overlay_candidate(element: Mapping[str, Any], bounds: Mapping[int, tuple[float, float]]) -> bool:
    page = _page_value(element)
    bbox = element.get("bbox")
    if page is None or not isinstance(bbox, Mapping):
        return False
    y0 = _coerce_float(bbox.get("y0"))
    y1 = _coerce_float(bbox.get("y1"))
    if y0 is None or y1 is None:
        return False
    top, bottom = bounds.get(int(page), (0.0, 0.0))
    height = max(1.0, float(bottom) - float(top))
    cy = ((float(y0) + float(y1)) / 2.0) - float(top)
    ratio = cy / height
    return 0.18 <= ratio <= 0.82


def _normalize_text(text: str) -> str:
    normalized = _SPACE_RE.sub("", str(text or "").strip().lower())
    return normalized


def _is_known_export_noise(text: str) -> bool:
    return classify_document_noise_text(text) is not None


def _is_removable_kind(kind: str) -> bool:
    return str(kind or "").strip().lower() not in {"table", "equation", "formula", "seal"}


def _repeated_overlay_key(
    element: Mapping[str, Any],
    *,
    bounds: Mapping[int, tuple[float, float]],
) -> tuple[str, tuple[int, int] | None] | None:
    text = _text_value(element)
    kind = _kind_value(element)
    page = _page_value(element)
    if not text or page is None or not _is_removable_kind(kind):
        return None
    normalized = _normalize_text(text)
    if (
        len(normalized) < 4
        or len(normalized) > 80
        or normalized in _COMMON_SHORT_REPEAT_TEXT
        or not _is_center_overlay_candidate(element, bounds)
    ):
        return None
    return normalized, _bbox_center_key(element)


def _collect_remove_indexes(
    original: Sequence[Mapping[str, Any]],
    *,
    bounds: Mapping[int, tuple[float, float]],
    threshold: int,
) -> tuple[set[int], dict[int, str]]:
    remove_indexes: set[int] = set()
    reason_by_index: dict[int, str] = {}
    repeated_candidates: dict[tuple[str, tuple[int, int] | None], list[tuple[int, int]]] = defaultdict(list)
    for index, element in enumerate(original):
        text = _text_value(element)
        if text and _is_known_export_noise(text):
            remove_indexes.add(index)
            reason_by_index[index] = "pdf_export_noise"
            continue
        candidate = _repeated_overlay_key(element, bounds=bounds)
        if candidate is None:
            continue
        page = _page_value(element)
        if page is not None:
            repeated_candidates[candidate].append((index, int(page)))

    for entries in repeated_candidates.values():
        candidate_pages = {page for _index, page in entries}
        if len(candidate_pages) < threshold:
            continue
        for index, _page in entries:
            remove_indexes.add(index)
            reason_by_index.setdefault(index, "repeated_overlay")
    return remove_indexes, reason_by_index


def _result_from_removed_indexes(
    original: Sequence[Mapping[str, Any]],
    *,
    pages: list[int],
    remove_indexes: set[int],
    reason_by_index: Mapping[int, str],
) -> WatermarkRemovalResult:
    kept: list[dict[str, Any]] = []
    removed_ids: list[str] = []
    reasons = Counter()
    for index, element in enumerate(original):
        if index in remove_indexes:
            removed_ids.append(str(element.get("id") or index))
            reasons[reason_by_index.get(index, "watermark_noise")] += 1
            continue
        kept.append(dict(element))
    return WatermarkRemovalResult(
        elements=kept,
        changed=True,
        removed_count=int(len(remove_indexes)),
        removed_ids=removed_ids,
        pages=pages,
        reasons=dict(reasons),
    )


def remove_document_watermark_elements(
    elements: Sequence[Mapping[str, Any]] | None,
    *,
    min_pages: int = 2,
) -> WatermarkRemovalResult:
    original = [dict(item) for item in (elements or []) if isinstance(item, Mapping)]
    if not original:
        return WatermarkRemovalResult(elements=[], changed=False, removed_count=0, removed_ids=[], pages=[])

    pages = sorted({int(page) for item in original if (page := _page_value(item)) is not None})
    bounds = _page_bounds(original)
    threshold = max(2, int(min_pages or 2))
    remove_indexes, reason_by_index = _collect_remove_indexes(original, bounds=bounds, threshold=threshold)
    if not remove_indexes:
        return WatermarkRemovalResult(elements=original, changed=False, removed_count=0, removed_ids=[], pages=pages)
    return _result_from_removed_indexes(
        original,
        pages=pages,
        remove_indexes=remove_indexes,
        reason_by_index=reason_by_index,
    )


__all__ = ["WatermarkRemovalResult", "remove_document_watermark_elements"]
