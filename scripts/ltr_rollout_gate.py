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

from app.services.ltr_rollout_workflow import (  # noqa: E402
    evaluate_ltr_rollout_gate,
    normalize_ltr_rollout_gate_thresholds,
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _extract_comparison(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and payload.get("schema") == "mimirq.ltr_rollout_workflow.v1":
        comparison = payload.get("comparison")
        if isinstance(comparison, dict):
            return comparison
        raise ValueError("workflow payload missing comparison object")
    if isinstance(payload, dict):
        return payload
    raise ValueError("input JSON must be an object")


def _load_thresholds(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("thresholds JSON must be an object")
    return normalize_ltr_rollout_gate_thresholds(payload)


def _merge_cli_overrides(*, base: dict[str, Any] | None, args: argparse.Namespace) -> dict[str, Any] | None:
    overrides: dict[str, dict[str, float]] = {}
    for metric, value in (
        ("delta.hit", args.min_delta_hit),
        ("delta.mrr", args.min_delta_mrr),
        ("delta.recall", args.min_delta_recall),
        ("delta.ndcg", args.min_delta_ndcg),
        ("candidate.cases_used", args.min_cases_used),
    ):
        if value is None:
            continue
        overrides[metric] = {"min": float(value)}

    if not overrides:
        return base

    merged = normalize_ltr_rollout_gate_thresholds(base)
    metrics = dict(merged.get("metrics") or {})
    metrics.update(overrides)
    merged["metrics"] = metrics
    return merged


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate LTR rollout gate against comparison/workflow JSON.")
    parser.add_argument("--input", required=True, help="Path to comparison.json or workflow.json")
    parser.add_argument("--thresholds", default="", help="Optional thresholds JSON path")
    parser.add_argument("--out", default="", help="Optional output path for gate result JSON")
    parser.add_argument("--min-delta-hit", type=float, default=None, help="Override threshold for delta.hit")
    parser.add_argument("--min-delta-mrr", type=float, default=None, help="Override threshold for delta.mrr")
    parser.add_argument("--min-delta-recall", type=float, default=None, help="Override threshold for delta.recall")
    parser.add_argument("--min-delta-ndcg", type=float, default=None, help="Override threshold for delta.ndcg")
    parser.add_argument("--min-cases-used", type=float, default=None, help="Override threshold for candidate.cases_used")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    input_path = Path(str(args.input))
    if not input_path.exists():
        print(f"[ltr_rollout_gate] ERROR: input file not found: {input_path}", file=sys.stderr)
        return 2

    thresholds_path = Path(str(args.thresholds)) if str(args.thresholds or "").strip() else None

    try:
        payload = _read_json(input_path)
        comparison = _extract_comparison(payload)
        thresholds = _load_thresholds(thresholds_path)
        thresholds = _merge_cli_overrides(base=thresholds, args=args)
        gate = evaluate_ltr_rollout_gate(comparison=comparison, thresholds=thresholds)
    except Exception as exc:
        print(f"[ltr_rollout_gate] ERROR: {str(exc)[:240]}", file=sys.stderr)
        return 2

    if str(args.out or "").strip():
        out_path = Path(str(args.out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "[ltr_rollout_gate]"
        f" passed={gate.get('passed')}"
        f" checks={gate.get('summary', {}).get('total')}"
        f" failed={gate.get('summary', {}).get('failed')}"
    )
    if gate.get("reasons"):
        for reason in list(gate.get("reasons") or []):
            print(f"[ltr_rollout_gate] reason: {reason}")

    return 0 if bool(gate.get("passed")) else 3


if __name__ == "__main__":
    raise SystemExit(main())
