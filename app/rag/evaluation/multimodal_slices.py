from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MULTIMODAL_GOLDEN_SLICE_SCHEMA_V1 = "mimirq.multimodal_golden_slices.v1"

_KNOWN_SLICES = ("chart", "formula", "table_math", "image", "text")

_CHART_HINTS = (
    "chart",
    "graph",
    "plot",
    "柱状图",
    "折线图",
    "饼图",
    "图表",
    "曲线",
)
_FORMULA_HINTS = (
    "formula",
    "equation",
    "latex",
    "sympy",
    "wolfram",
    "公式",
    "方程",
    "计算式",
)
_TABLE_MATH_HINTS = (
    "table_math",
    "table-math",
    "table math",
    "spreadsheet",
    "table",
    "表格",
    "占比",
    "同比",
    "环比",
    "top 3",
    "top3",
    "前 3",
    "前3",
    "排名",
    "cagr",
)
_IMAGE_HINTS = ("image", "vision", "clip", "图片", "图像", "截图", "扫描件")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        try:
            return dict(value.model_dump(mode="json"))
        except Exception:
            return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _text(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _normalize_slice(value: Any) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    compact = raw.replace(" ", "-")
    if compact in {"chart", "graph", "plot"}:
        return "chart"
    if compact in {"formula", "equation", "latex", "math"}:
        return "formula"
    if compact in {"table", "table-math", "spreadsheet", "tabular"}:
        return "table_math"
    if compact in {"image", "vision", "clip"}:
        return "image"
    if compact == "text":
        return "text"
    return None


def _hinted_slice(text: str) -> str | None:
    lowered = _text(text)
    if not lowered:
        return None
    for hint in _CHART_HINTS:
        if hint in lowered:
            return "chart"
    for hint in _FORMULA_HINTS:
        if hint in lowered:
            return "formula"
    for hint in _TABLE_MATH_HINTS:
        if hint in lowered:
            return "table_math"
    for hint in _IMAGE_HINTS:
        if hint in lowered:
            return "image"
    return None


def classify_regression_case_multimodal_slice(case: Any) -> str:
    """
    Classify a Golden regression case into stable multimodal slices.

    Explicit case.extra fields and tags win over heuristic question matching so
    hand-curated Golden suites remain deterministic.
    """
    extra = _as_dict(_get(case, "extra", None))
    for key in (
        "golden_multimodal_slice",
        "multimodal_slice",
        "slice_modality",
        "case_type",
        "task_type",
        "modality",
        "query_modality",
    ):
        normalized = _normalize_slice(extra.get(key))
        if normalized:
            return normalized

    tag_text = " ".join(str(tag or "") for tag in _as_list(_get(case, "tags", None)))
    tagged = _normalize_slice(tag_text) or _hinted_slice(tag_text)
    if tagged:
        return tagged

    question = str(_get(case, "question", "") or "")
    hinted = _hinted_slice(question)
    if hinted:
        return hinted

    reference_text_parts: list[str] = []
    for src in _as_list(_get(case, "reference_sources", None)):
        src_d = _as_dict(src)
        reference_text_parts.extend(
            str(src_d.get(key) or "") for key in ("label", "quote", "hit_type", "source_type") if src_d.get(key)
        )
    hinted = _hinted_slice(" ".join(reference_text_parts))
    return hinted or "text"


def summarize_multimodal_regression_slices(eval_items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = dict.fromkeys(_KNOWN_SLICES, 0)
    evaluatable = dict.fromkeys(_KNOWN_SLICES, 0)
    abstained = dict.fromkeys(_KNOWN_SLICES, 0)

    for item in eval_items or []:
        meta = item.get("item_meta") if isinstance(item.get("item_meta"), dict) else {}
        raw_slice = meta.get("golden_multimodal_slice") or meta.get("slice_modality") or "text"
        slice_key = _normalize_slice(raw_slice) or "text"
        if slice_key not in counts:
            slice_key = "text"

        counts[slice_key] += 1
        contexts = _as_list(item.get("retrieved_contexts"))
        citations = _as_list(item.get("citations"))
        if any(str(ctx or "").strip() for ctx in contexts) or bool(citations):
            evaluatable[slice_key] += 1
        if bool(item.get("abstain_triggered")):
            abstained[slice_key] += 1

    coverage = {
        key: round(float(evaluatable[key]) / float(count), 4) if (count := counts[key]) else 0.0
        for key in _KNOWN_SLICES
    }

    return {
        "schema": MULTIMODAL_GOLDEN_SLICE_SCHEMA_V1,
        "items": sum(counts.values()),
        "counts": counts,
        "evaluatable": evaluatable,
        "abstained": abstained,
        "coverage": coverage,
    }
