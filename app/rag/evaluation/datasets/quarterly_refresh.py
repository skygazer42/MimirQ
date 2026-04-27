from __future__ import annotations

import hashlib
from typing import Any

from app.rag.evaluation.datasets.schema import normalize_eval_dataset_sample

QUARTERLY_REFRESH_SCHEMA_V1 = "mimirq.eval.dataset.quarterly_refresh.v1"


def _stable_rank(*, quarter_key: str, sample_id: str) -> str:
    raw = f"{quarter_key}|{sample_id}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _normalize_ratio(value: float | int | None) -> float:
    try:
        ratio = float(value if value is not None else 0.2)
    except Exception:
        ratio = 0.2
    return max(0.0, min(1.0, ratio))


def plan_quarterly_refresh(
    *,
    rows: list[dict[str, Any]],
    quarter_key: str,
    refresh_ratio: float = 0.2,
) -> dict[str, Any]:
    normalized_rows = [normalize_eval_dataset_sample(dict(row or {})) for row in (rows or []) if isinstance(row, dict)]
    quarter = str(quarter_key or "").strip() or "unknown"
    ratio = _normalize_ratio(refresh_ratio)

    ranked = sorted(
        normalized_rows,
        key=lambda row: (
            _stable_rank(quarter_key=quarter, sample_id=str(row.get("sample_id") or "")),
            str(row.get("sample_id") or ""),
        ),
    )

    total = len(ranked)
    refresh_count = 0
    if total > 0 and ratio > 0.0:
        refresh_count = max(1, int(round(total * ratio)))
        refresh_count = min(refresh_count, total)

    refresh_rows: list[dict[str, Any]] = []
    stable_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(ranked):
        row_copy = dict(row)
        if idx < refresh_count:
            tags = [str(tag).strip() for tag in (row_copy.get("tags") or []) if str(tag or "").strip()]
            if "quarterly_refresh" not in tags:
                tags.append("quarterly_refresh")
            row_copy["tags"] = tags
            row_copy["refresh_quarter"] = quarter
            row_copy["refresh_action"] = "regenerate"
            refresh_rows.append(row_copy)
        else:
            stable_rows.append(row_copy)

    return {
        "schema": QUARTERLY_REFRESH_SCHEMA_V1,
        "quarter_key": quarter,
        "refresh_ratio": ratio,
        "summary": {
            "total_samples": int(total),
            "refresh_samples": int(len(refresh_rows)),
            "stable_samples": int(len(stable_rows)),
        },
        "refresh_sample_ids": [str(row.get("sample_id") or "") for row in refresh_rows],
        "stable_sample_ids": [str(row.get("sample_id") or "") for row in stable_rows],
        "refresh_rows": refresh_rows,
        "stable_rows": stable_rows,
    }


__all__ = ["QUARTERLY_REFRESH_SCHEMA_V1", "plan_quarterly_refresh"]
