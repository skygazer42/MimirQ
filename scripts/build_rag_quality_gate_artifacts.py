#!/usr/bin/env python3


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


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except Exception:
        return None


def extract_benchmark_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _load_thresholds(path: Path) -> dict[str, dict[str, float]]:
    payload = _load_json(path)
    root = payload.get("ci_retrieval_only_bounded_gate") if isinstance(payload, dict) else {}
    thresholds = root.get("thresholds") if isinstance(root, dict) else {}
    out: dict[str, dict[str, float]] = {}
    metric_names = {
        "mrr": "retrieval_mrr",
        "ndcg_at_k": "retrieval_ndcg_at_k",
        "hit_at_k": "retrieval_hit_at_k",
    }
    for metric, cfg in (thresholds or {}).items():
        if not isinstance(cfg, dict):
            continue
        row: dict[str, float] = {}
        if cfg.get("min") is not None:
            row["min"] = float(cfg.get("min"))
        if cfg.get("max") is not None:
            row["max"] = float(cfg.get("max"))
        if row:
            out[metric_names.get(str(metric), str(metric))] = row
    return out


def build_retrieval_ranking_proxy_summary(benchmark_payload: Any) -> dict[str, Any]:
    summary = extract_benchmark_summary(benchmark_payload)
    return {
        "schema": "mimirq.retrieval_ranking_proxy_summary.v1",
        "retrieval_mrr": _coerce_optional_float(summary.get("mrr")),
        "retrieval_ndcg_at_k": _coerce_optional_float(
            summary.get("ndcg_at_k") if summary.get("ndcg_at_k") is not None else summary.get("family_ndcg_at_k")
        ),
        "retrieval_hit_at_k": _coerce_optional_float(summary.get("hit_at_k")),
    }


def build_retrieval_ranking_proxy_gate_report(
    summary_payload: Any,
    *,
    summary_path: str,
    thresholds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    if not isinstance(summary_payload, dict):
        summary_payload = {}
    values = {
        "retrieval_mrr": _coerce_optional_float(summary_payload.get("retrieval_mrr")),
        "retrieval_ndcg_at_k": _coerce_optional_float(summary_payload.get("retrieval_ndcg_at_k")),
        "retrieval_hit_at_k": _coerce_optional_float(summary_payload.get("retrieval_hit_at_k")),
    }
    checks = {}
    for name, value in values.items():
        cfg = thresholds.get(name) or {}
        minimum = cfg.get("min")
        maximum = cfg.get("max")
        passed = bool(cfg) and value is not None
        reason = None
        if not cfg:
            reason = "missing_threshold"
        elif value is None:
            reason = "missing_metric"
        elif minimum is not None and value < float(minimum):
            passed = False
            reason = "lt_min"
        if value is not None and maximum is not None and value > float(maximum):
            passed = False
            reason = "gt_max"
        checks[name] = {
            "value": value,
            "min": minimum,
            "max": maximum,
            "passed": passed,
            "reason": reason,
        }
    return {
        "schema": "mimirq.retrieval_ranking_proxy_gate_report.v1",
        "summary_path": str(summary_path),
        "thresholds": thresholds,
        "checks": checks,
        "passed": bool(all(item["passed"] for item in checks.values())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build honest retrieval-ranking proxy artifacts.")
    parser.add_argument("--benchmark", required=True, help="Input sample retrieval benchmark JSON path.")
    parser.add_argument(
        "--thresholds",
        default="ci/retrieval_thresholds.v2.json",
        help="Thresholds JSON path (default: %(default)s).",
    )
    parser.add_argument(
        "--summary-out",
        default="artifacts/retrieval_ranking_proxy.summary.json",
        help="Output retrieval-ranking proxy summary JSON path.",
    )
    parser.add_argument(
        "--report-out",
        default="artifacts/retrieval_ranking_proxy_gate.report.json",
        help="Output retrieval-ranking proxy gate report JSON path.",
    )
    args = parser.parse_args(argv)

    benchmark_path = Path(str(args.benchmark)).expanduser().resolve()
    thresholds_path = Path(str(args.thresholds)).expanduser().resolve()
    summary_path_arg = str(args.summary_out)
    report_path_arg = str(args.report_out)
    summary_path = Path(summary_path_arg).expanduser()
    report_path = Path(report_path_arg).expanduser()

    if not benchmark_path.exists():
        raise SystemExit(f"benchmark_not_found: {benchmark_path}")
    if not thresholds_path.exists():
        raise SystemExit(f"thresholds_not_found: {thresholds_path}")

    benchmark_payload = _load_json(benchmark_path)
    summary_payload = build_retrieval_ranking_proxy_summary(benchmark_payload)
    threshold_cfg = _load_thresholds(thresholds_path)
    report_payload = build_retrieval_ranking_proxy_gate_report(
        summary_payload,
        summary_path=summary_path_arg,
        thresholds=threshold_cfg,
    )

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[retrieval-ranking-proxy] wrote {summary_path}")
    print(f"[retrieval-ranking-proxy] wrote {report_path}")
    return 0 if bool(report_payload.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
