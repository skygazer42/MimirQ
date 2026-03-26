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


def extract_benchmark_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def build_answer_quality_summary(benchmark_payload: Any) -> dict[str, Any]:
    summary = extract_benchmark_summary(benchmark_payload)
    answer_relevancy = _coerce_float(summary.get("ndcg_at_k"), default=_coerce_float(summary.get("family_ndcg_at_k")))
    return {
        "schema": "mimirq.answer_quality_summary.v1",
        # Retrieval-only CI uses deterministic ranking quality proxies until model-graded evals are wired in.
        "faithfulness": _coerce_float(summary.get("mrr")),
        "answer_relevancy": answer_relevancy,
        "context_precision": _coerce_float(summary.get("hit_at_k")),
    }


def build_rag_quality_gate_report(
    summary_payload: Any,
    *,
    summary_path: str,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    if not isinstance(summary_payload, dict):
        summary_payload = {}
    values = {
        "faithfulness": _coerce_float(summary_payload.get("faithfulness")),
        "answer_relevancy": _coerce_float(summary_payload.get("answer_relevancy")),
        "context_precision": _coerce_float(summary_payload.get("context_precision")),
    }
    checks = {
        name: {
            "value": values[name],
            "min": float(thresholds[name]),
            "passed": bool(values[name] >= float(thresholds[name])),
        }
        for name in values
    }
    return {
        "schema": "mimirq.rag_quality_gate_report.v1",
        "summary_path": str(summary_path),
        "thresholds": {name: float(value) for name, value in thresholds.items()},
        "checks": checks,
        "passed": bool(all(item["passed"] for item in checks.values())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic RAG quality gate artifacts.")
    parser.add_argument("--benchmark", required=True, help="Input sample retrieval benchmark JSON path.")
    parser.add_argument(
        "--summary-out",
        default="artifacts/answer_quality.summary.json",
        help="Output answer-quality summary JSON path.",
    )
    parser.add_argument(
        "--report-out",
        default="artifacts/rag_quality_gate.report.json",
        help="Output RAG quality gate report JSON path.",
    )
    args = parser.parse_args(argv)

    benchmark_path = Path(str(args.benchmark)).expanduser().resolve()
    summary_path = Path(str(args.summary_out)).expanduser().resolve()
    report_path = Path(str(args.report_out)).expanduser().resolve()

    if not benchmark_path.exists():
        raise SystemExit(f"benchmark_not_found: {benchmark_path}")

    benchmark_payload = _load_json(benchmark_path)
    summary_payload = build_answer_quality_summary(benchmark_payload)

    from app.core.config import Settings

    cfg = Settings()
    thresholds = {
        "faithfulness": float(cfg.RAG_EVAL_GATE_FAITHFULNESS_MIN),
        "answer_relevancy": float(cfg.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN),
        "context_precision": float(cfg.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN),
    }
    report_payload = build_rag_quality_gate_report(
        summary_payload,
        summary_path=str(summary_path),
        thresholds=thresholds,
    )

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[rag-quality-gate] wrote {summary_path}")
    print(f"[rag-quality-gate] wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
