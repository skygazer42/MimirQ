#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_case_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    while text.endswith("_case"):
        text = text[: -len("_case")]
    return text


def _mean(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    total = sum(_coerce_float(row.get(field)) for row in rows)
    return round(total / float(len(rows)), 6)


def _classify_case_category(case_id: Any) -> str:
    normalized = _normalize_case_id(case_id)
    if "table" in normalized:
        return "table"
    if any(token in normalized for token in ("layout", "column", "header_footer", "mixed")):
        return "layout"
    if any(token in normalized for token in ("image", "chart", "diagram", "qr", "barcode")):
        return "image"
    return "other"


def _classify_case_slice(case_id: Any) -> str:
    normalized = _normalize_case_id(case_id)
    for slice_name in (
        "line_chart",
        "cross_page_table",
        "borderless_table",
        "merged_header_table",
        "table_with_leading_paragraph",
        "two_column",
        "header_footer_noise",
        "mixed_layout",
        "chart",
        "diagram",
        "qr",
        "barcode",
        "table",
        "layout",
        "image",
    ):
        if slice_name in normalized:
            return slice_name
    return "other"


def _build_group_summaries(
    case_rows: list[dict[str, Any]],
    *,
    classifier,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in case_rows:
        group_name = str(classifier(row.get("id")) or "other").strip() or "other"
        grouped.setdefault(group_name, []).append(row)

    summaries: list[dict[str, Any]] = []
    for group_name in sorted(grouped):
        rows = grouped[group_name]
        failed_case_ids = [str(item.get("id") or "").strip() for item in rows if _coerce_float(item.get("hit_at_k")) < 1.0 or _coerce_float(item.get("mrr")) < 1.0]
        summaries.append(
            {
                "name": group_name,
                "cases_total": len(rows),
                "case_ids": [str(item.get("id") or "").strip() for item in rows if str(item.get("id") or "").strip()],
                "hit_at_k_mean": _mean(rows, "hit_at_k"),
                "mrr_mean": _mean(rows, "mrr"),
                "failed_case_ids": failed_case_ids,
            }
        )
    return summaries


def _normalize_count_map(value: Any) -> dict[str, int]:
    payload = value if isinstance(value, dict) else {}
    out: dict[str, int] = {}
    for key in sorted(payload):
        try:
            count = int(payload.get(key) or 0)
        except Exception:
            continue
        if count > 0:
            out[str(key)] = count
    return out


def _build_rollout_summary(rollout_payload: Any) -> dict[str, Any] | None:
    payload = rollout_payload if isinstance(rollout_payload, dict) else {}
    current_stage = str(payload.get("current_stage") or "").strip().lower()
    if current_stage not in {"informational", "warn", "fail"}:
        return None

    next_stage: str | None = None
    promotion_key: str | None = None
    if current_stage == "informational":
        next_stage = "warn"
        promotion_key = "informational_to_warn"
    elif current_stage == "warn":
        next_stage = "fail"
        promotion_key = "warn_to_fail"

    promotion_requirements_obj = (
        payload.get("promotion_requirements")
        if isinstance(payload.get("promotion_requirements"), dict)
        else {}
    )
    promotion_requirements = []
    if promotion_key is not None:
        promotion_requirements = [
            str(value).strip()
            for value in (promotion_requirements_obj.get(promotion_key) or [])
            if str(value).strip()
        ]

    owner_roles = [
        str(value).strip()
        for value in (payload.get("owner_roles") or [])
        if str(value).strip()
    ]
    return {
        "schema": str(payload.get("schema") or "").strip(),
        "current_stage": current_stage,
        "next_stage": next_stage,
        "owner_roles": owner_roles,
        "promotion_requirements": promotion_requirements,
    }


def build_parsing_proof_summary(batch_payload: Any) -> dict[str, Any]:
    payload = batch_payload if isinstance(batch_payload, dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [item for item in raw_cases if isinstance(item, dict)]

    case_summaries: list[dict[str, Any]] = []
    failed_cases: list[str] = []
    for case in cases:
        case_summary = case.get("summary") if isinstance(case.get("summary"), dict) else {}
        hit = _coerce_float(case_summary.get("hit_at_k"))
        mrr = _coerce_float(case_summary.get("mrr"))
        case_id = str(case.get("id") or "").strip()
        row = {
            "id": case_id or None,
            "hit_at_k": hit,
            "mrr": mrr,
        }
        case_summaries.append(row)
        if hit < 1.0 or mrr < 1.0:
            failed_cases.append(case_id)

    category_summaries = _build_group_summaries(case_summaries, classifier=_classify_case_category)
    slice_summaries = _build_group_summaries(case_summaries, classifier=_classify_case_slice)

    return {
        "schema": "mimirq.parsing_retrieval_proof_summary.v1",
        "cases_total": int(payload.get("cases_total") or len(cases)),
        "query_count_total": int(payload.get("query_count_total") or 0),
        "hit_at_k_mean": _coerce_float(summary.get("hit_at_k_mean")),
        "mrr_mean": _coerce_float(summary.get("mrr_mean")),
        "failed_case_ids": [item for item in failed_cases if item],
        "sample_composition": {
            "case_family_counts": _normalize_count_map(payload.get("case_family_counts")),
            "case_category_counts": _normalize_count_map(payload.get("case_category_counts")),
        },
        "cases": case_summaries,
        "category_summaries": category_summaries,
        "slice_summaries": slice_summaries,
    }


def build_parsing_proof_report(
    summary_payload: Any,
    *,
    summary_path: str,
    thresholds: dict[str, float],
    rollout: Any = None,
) -> dict[str, Any]:
    payload = summary_payload if isinstance(summary_payload, dict) else {}
    values = {
        "hit_at_k_mean": _coerce_float(payload.get("hit_at_k_mean")),
        "mrr_mean": _coerce_float(payload.get("mrr_mean")),
    }
    checks = {
        name: {
            "value": values[name],
            "min": float(thresholds[name]),
            "passed": bool(values[name] >= float(thresholds[name])),
        }
        for name in values
    }
    report = {
        "schema": "mimirq.parsing_retrieval_proof_report.v1",
        "summary_path": str(summary_path),
        "thresholds": {name: float(value) for name, value in thresholds.items()},
        "checks": checks,
        "failed_case_ids": list(payload.get("failed_case_ids") or []),
        "query_count_total": int(payload.get("query_count_total") or 0),
        "sample_composition": {
            "case_family_counts": _normalize_count_map((payload.get("sample_composition") or {}).get("case_family_counts")),
            "case_category_counts": _normalize_count_map((payload.get("sample_composition") or {}).get("case_category_counts")),
        },
        "category_summaries": list(payload.get("category_summaries") or []),
        "slice_summaries": list(payload.get("slice_summaries") or []),
        "passed": bool(all(item["passed"] for item in checks.values())),
    }
    rollout_summary = _build_rollout_summary(rollout)
    if rollout_summary is not None:
        report["rollout"] = rollout_summary
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic parsing-proof summary/report artifacts from a batch proof report.")
    parser.add_argument("--batch-report", required=True, help="Input parsing proof batch report JSON path.")
    parser.add_argument("--summary-out", required=True, help="Output parsing proof summary JSON path.")
    parser.add_argument("--report-out", required=True, help="Output parsing proof report JSON path.")
    parser.add_argument("--min-hit-at-k-mean", type=float, default=1.0, help="Minimum acceptable hit_at_k_mean.")
    parser.add_argument("--min-mrr-mean", type=float, default=1.0, help="Minimum acceptable mrr_mean.")
    args = parser.parse_args(argv)

    batch_report_path = Path(str(args.batch_report)).expanduser().resolve()
    summary_out_arg = str(args.summary_out)
    report_out_arg = str(args.report_out)
    summary_out_path = Path(summary_out_arg).expanduser()
    report_out_path = Path(report_out_arg).expanduser()
    if not batch_report_path.exists():
        raise SystemExit(f"batch_report_not_found: {batch_report_path}")

    batch_payload = _load_json(batch_report_path)
    summary_payload = build_parsing_proof_summary(batch_payload)
    report_payload = build_parsing_proof_report(
        summary_payload,
        summary_path=summary_out_arg,
        thresholds={
            "hit_at_k_mean": float(args.min_hit_at_k_mean),
            "mrr_mean": float(args.min_mrr_mean),
        },
    )

    summary_out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_out_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_out_path.parent.mkdir(parents=True, exist_ok=True)
    report_out_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[parsing-proof-artifacts] wrote {summary_out_path}")
    print(f"[parsing-proof-artifacts] wrote {report_out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
