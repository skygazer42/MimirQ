#!/usr/bin/env python3
"""
Build a deterministic reparse candidate plan from dataset report parse-risk summary.
"""


import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"report root must be object: {path}")
    return obj


def _coerce_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _coerce_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def run(
    *,
    report_path: Path,
    out: Path | None,
    max_docs: int | None,
    max_score: float | None,
) -> dict[str, Any]:
    report = _load_json(report_path)
    parse_risk = report.get("parse_risk_summary") if isinstance(report.get("parse_risk_summary"), dict) else {}
    candidates_raw = (
        parse_risk.get("top_low_quality_documents")
        if isinstance(parse_risk.get("top_low_quality_documents"), list)
        else []
    )
    low_threshold = _coerce_float(parse_risk.get("low_threshold"), 0.35)
    cutoff = float(max_score) if max_score is not None else float(low_threshold)
    cap = max(1, int(max_docs or 100))

    rows: list[tuple[str, float]] = []
    specialty_meta: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for item in candidates_raw:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("document_id") or "").strip()
        if not doc_id or doc_id in seen:
            continue
        score = _coerce_float(item.get("score"), 1.0)
        if score > cutoff:
            continue
        seen.add(doc_id)
        rows.append((doc_id, score))
        specialty_meta[doc_id] = {
            "reason": str(item.get("reason") or "").strip() or "parse_quality_below_threshold",
            "specialty_signals": dict(item.get("specialty_signals") or {}) if isinstance(item.get("specialty_signals"), dict) else {},
        }

    rows.sort(key=lambda x: (x[1], x[0]))
    rows = rows[:cap]

    payload: dict[str, Any] = {
        "schema": "mimirq.parse_quality_reparse_plan.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_report": str(report_path),
        "dataset_id": str(report.get("dataset_id") or ""),
        "low_threshold": round(float(low_threshold), 3),
        "max_score": round(float(cutoff), 3),
        "recommendation": str(parse_risk.get("recommendation") or ""),
        "summary": {
            "considered_documents": _coerce_int(parse_risk.get("considered_documents"), 0),
            "high_risk_documents": _coerce_int(parse_risk.get("high_risk_documents"), 0),
            "selected_candidates": int(len(rows)),
        },
        "candidates": [
            {
                "document_id": doc_id,
                "score": round(float(score), 3),
                "reason": str((specialty_meta.get(doc_id) or {}).get("reason") or "parse_quality_below_threshold"),
                "specialty_signals": dict((specialty_meta.get(doc_id) or {}).get("specialty_signals") or {}),
            }
            for doc_id, score in rows
        ],
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build parse-quality reparse candidates from report JSON")
    p.add_argument("--report", required=True, help="Path to dataset report JSON")
    p.add_argument("--out", default="", help="Optional output JSON path")
    p.add_argument("--max-docs", type=int, default=100, help="Max candidate documents to include")
    p.add_argument(
        "--max-score",
        type=float,
        default=None,
        help="Optional max parse_quality score cutoff (defaults to report low_threshold)",
    )
    p.add_argument("--compact", action="store_true", help="Print compact one-line JSON")
    args = p.parse_args(argv)

    try:
        payload = run(
            report_path=Path(args.report),
            out=Path(args.out) if str(args.out or "").strip() else None,
            max_docs=max(1, int(args.max_docs or 1)),
            max_score=(float(args.max_score) if args.max_score is not None else None),
        )
    except Exception as exc:
        print(f"[plan_parse_quality_reparse] ERROR: {exc}", file=sys.stderr)
        return 1

    if args.compact:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
