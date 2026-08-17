#!/usr/bin/env python3
"""
Verify parse-repair effectiveness by checking parse-risk tail shrinkage.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _maybe_add_document_id(ids: set[str], value: Any) -> None:
    doc = str(value or "").strip()
    if doc:
        ids.add(doc)


def _collect_action_ids(actions: Any, ids: set[str]) -> None:
    if not isinstance(actions, list):
        return
    for item in actions:
        if isinstance(item, dict):
            _maybe_add_document_id(ids, item.get("document_id"))


def _collect_parse_risk_summary_ids(summary: Any, ids: set[str]) -> None:
    if not isinstance(summary, dict):
        return
    for key in ("parse_risk_tail", "top_low_quality_documents"):
        rows = summary.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict):
                _maybe_add_document_id(ids, item.get("document_id"))


def _collect_drift_ids(drift: Any, ids: set[str]) -> None:
    if not isinstance(drift, dict):
        return
    for key in ("retained_document_ids", "added_document_ids"):
        rows = drift.get(key)
        if not isinstance(rows, list):
            continue
        for raw in rows:
            _maybe_add_document_id(ids, raw)


def _extract_tail_from_payload(obj: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(obj, list):
        for item in obj:
            ids.update(_extract_tail_from_payload(item))
        return ids
    if not isinstance(obj, dict):
        return ids

    _collect_action_ids(obj.get("actions"), ids)
    _collect_parse_risk_summary_ids(obj.get("parse_risk_summary"), ids)
    _collect_drift_ids(obj.get("parse_risk_tail_drift"), ids)
    for value in obj.values():
        if isinstance(value, (dict, list)):
            ids.update(_extract_tail_from_payload(value))
    return ids


def evaluate_parse_repair_gate(
    *,
    baseline_payload: Any,
    current_payload: Any,
    min_shrinkage: float,
    max_added_tail: int,
    max_current_tail: int,
) -> dict[str, Any]:
    base_tail = _extract_tail_from_payload(baseline_payload)
    cur_tail = _extract_tail_from_payload(current_payload)

    removed = sorted(base_tail - cur_tail)
    added = sorted(cur_tail - base_tail)
    retained = sorted(base_tail & cur_tail)

    baseline_count = len(base_tail)
    current_count = len(cur_tail)
    shrinkage = (
        (float(baseline_count - current_count) / float(max(1, baseline_count)))
        if baseline_count > 0
        else (1.0 if current_count == 0 else 0.0)
    )

    failures: list[str] = []
    if float(shrinkage) < float(min_shrinkage):
        failures.append(f"shrinkage={shrinkage:.4f} < min_shrinkage={float(min_shrinkage):.4f}")
    if int(len(added)) > int(max_added_tail):
        failures.append(f"added_tail={len(added)} > max_added_tail={int(max_added_tail)}")
    if int(max_current_tail) >= 0 and int(current_count) > int(max_current_tail):
        failures.append(f"current_tail={current_count} > max_current_tail={int(max_current_tail)}")

    return {
        "schema": "mimirq.parse_repair_gate_report.v1",
        "generated_at": _now_utc_iso(),
        "policy": {
            "min_shrinkage": round(float(min_shrinkage), 4),
            "max_added_tail": int(max_added_tail),
            "max_current_tail": int(max_current_tail),
        },
        "observed": {
            "baseline_tail_count": int(baseline_count),
            "current_tail_count": int(current_count),
            "shrinkage": round(float(shrinkage), 4),
            "added_tail_count": int(len(added)),
            "removed_tail_count": int(len(removed)),
            "retained_tail_count": int(len(retained)),
            "added_document_ids": added[:200],
            "removed_document_ids": removed[:200],
        },
        "passed": len(failures) == 0,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verify parse-repair gate from baseline/current risk artifacts.")
    p.add_argument("--baseline", required=True, help="Baseline parse-risk artifact JSON")
    p.add_argument("--current", required=True, help="Current parse-risk artifact JSON")
    p.add_argument("--min-shrinkage", type=float, default=0.2)
    p.add_argument("--max-added-tail", type=int, default=0)
    p.add_argument("--max-current-tail", type=int, default=-1, help="-1 means ignore this check")
    p.add_argument("--out", default="artifacts/parse_repair_gate.report.json")
    args = p.parse_args(argv)

    baseline_path = Path(str(args.baseline)).expanduser().resolve()
    current_path = Path(str(args.current)).expanduser().resolve()
    if not baseline_path.exists():
        raise SystemExit(f"baseline_not_found:{baseline_path}")
    if not current_path.exists():
        raise SystemExit(f"current_not_found:{current_path}")

    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    current_payload = json.loads(current_path.read_text(encoding="utf-8"))

    report = evaluate_parse_repair_gate(
        baseline_payload=baseline_payload,
        current_payload=current_payload,
        min_shrinkage=max(0.0, min(1.0, _safe_float(args.min_shrinkage, 0.2))),
        max_added_tail=max(0, int(args.max_added_tail or 0)),
        max_current_tail=int(args.max_current_tail),
    )
    out_path = Path(str(args.out)).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[verify-parse-repair-gate] wrote {out_path}")
    print(f"[verify-parse-repair-gate] passed={bool(report.get('passed'))}")
    return 0 if bool(report.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
