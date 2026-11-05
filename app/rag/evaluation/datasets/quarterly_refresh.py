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
    normalized_rows = [normalize_eval_dataset_sample(row) for row in (rows or []) if isinstance(row, dict)]
    quarter = str(quarter_key or "").strip() or "unknown"
    ratio = _normalize_ratio(refresh_ratio)

    ranked = sorted(
        normalized_rows,
        key=lambda row: (
            _stable_rank(quarter_key=quarter, sample_id=row["sample_id"]),
            row["sample_id"],
        ),
    )

    total = len(ranked)
    refresh_count = 0
    if total > 0 and ratio > 0.0:
        refresh_count = max(1, round(total * ratio))
        refresh_count = min(refresh_count, total)

    refresh_rows: list[dict[str, Any]] = []
    stable_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(ranked):
        row_copy = dict(row)
        if idx < refresh_count:
            tags = list(row_copy["tags"])
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
            "total_samples": total,
            "refresh_samples": len(refresh_rows),
            "stable_samples": len(stable_rows),
        },
        "refresh_sample_ids": [row["sample_id"] for row in refresh_rows],
        "stable_sample_ids": [row["sample_id"] for row in stable_rows],
        "refresh_rows": refresh_rows,
        "stable_rows": stable_rows,
    }


__all__ = ["QUARTERLY_REFRESH_SCHEMA_V1", "plan_quarterly_refresh"]
