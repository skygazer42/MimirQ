"""Human-label calibration contract for the unified LLM judge."""


from collections import Counter
from datetime import datetime
from typing import Any

CALIBRATION_SCHEMA = "mimirq.llm_judge_calibration.v1"
CALIBRATION_LABELS = ("supported", "partial", "unsupported")


def _required_version(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if len(value) < 3:
        raise ValueError(f"calibration_{key}_required")
    return value


def _parse_reviewed_at(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return raw


def validate_calibration_payload(payload: Any, *, min_items: int = 50) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or str(payload.get("schema") or "").strip() != CALIBRATION_SCHEMA:
        raise ValueError(f"invalid_calibration_schema:{CALIBRATION_SCHEMA}")
    _required_version(payload, "judge_version_hash")
    _required_version(payload, "dataset_version")
    _required_version(payload, "label_policy_version")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ValueError("calibration_items_required")
    if len(rows) < max(1, int(min_items or 1)):
        raise ValueError(f"calibration_min_items:{max(1, int(min_items or 1))}")

    normalized: list[dict[str, str]] = []
    seen_case_ids: set[str] = set()
    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, dict):
            raise ValueError(f"calibration_item_invalid:{index}")
        case_id = str(raw_row.get("case_id") or "").strip()
        if not case_id or case_id in seen_case_ids:
            raise ValueError(f"calibration_case_id_invalid:{index}")
        human_label = str(raw_row.get("human_label") or "").strip().lower()
        judge_label = str(raw_row.get("judge_label") or "").strip().lower()
        if human_label not in CALIBRATION_LABELS or judge_label not in CALIBRATION_LABELS:
            raise ValueError(f"calibration_label_invalid:{case_id}")
        reviewer_hash = str(raw_row.get("reviewer_hash") or "").strip()
        if len(reviewer_hash) < 8:
            raise ValueError(f"calibration_reviewer_hash_invalid:{case_id}")
        reviewed_at = _parse_reviewed_at(raw_row.get("reviewed_at"))
        if reviewed_at is None:
            raise ValueError(f"calibration_reviewed_at_invalid:{case_id}")
        seen_case_ids.add(case_id)
        normalized.append(
            {
                "case_id": case_id,
                "human_label": human_label,
                "judge_label": judge_label,
                "reviewer_hash": reviewer_hash,
                "reviewed_at": reviewed_at,
            }
        )
    return normalized


def cohens_kappa(rows: list[dict[str, str]]) -> float | None:
    if not rows:
        return None
    total = float(len(rows))
    observed = sum(1 for row in rows if row["human_label"] == row["judge_label"]) / total
    human_counts = Counter(row["human_label"] for row in rows)
    judge_counts = Counter(row["judge_label"] for row in rows)
    expected = sum((human_counts[label] / total) * (judge_counts[label] / total) for label in CALIBRATION_LABELS)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return round((observed - expected) / (1.0 - expected), 4)


def build_calibration_report(
    payload: Any,
    *,
    min_items: int = 50,
    min_kappa: float = 0.6,
) -> dict[str, Any]:
    rows = validate_calibration_payload(payload, min_items=min_items)
    payload_dict = payload if isinstance(payload, dict) else {}
    kappa = cohens_kappa(rows)
    confusion: dict[str, dict[str, int]] = {
        human: {judge: 0 for judge in CALIBRATION_LABELS}
        for human in CALIBRATION_LABELS
    }
    for row in rows:
        confusion[row["human_label"]][row["judge_label"]] += 1
    reviewer_count = len({row["reviewer_hash"] for row in rows})
    passed = kappa is not None and float(kappa) >= float(min_kappa)
    return {
        "schema": "mimirq.llm_judge_calibration_report.v1",
        "items": len(rows),
        "reviewer_count": reviewer_count,
        "judge_version_hash": _required_version(payload_dict, "judge_version_hash"),
        "dataset_version": _required_version(payload_dict, "dataset_version"),
        "label_policy_version": _required_version(payload_dict, "label_policy_version"),
        "cohens_kappa": kappa,
        "min_items": int(min_items),
        "min_kappa": float(min_kappa),
        "passed": passed,
        "confusion": confusion,
    }


__all__ = [
    "CALIBRATION_LABELS",
    "CALIBRATION_SCHEMA",
    "build_calibration_report",
    "cohens_kappa",
    "validate_calibration_payload",
]
