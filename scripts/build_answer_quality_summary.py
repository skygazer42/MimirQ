#!/usr/bin/env python3


import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def extract_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    run = payload.get("run")
    if isinstance(run, dict) and isinstance(run.get("summary"), dict):
        return dict(run.get("summary") or {})
    summary = payload.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def build_answer_quality_summary(payload: Any) -> dict[str, Any]:
    summary = extract_summary(payload)
    return {
        "schema": "mimirq.answer_quality_summary.v2",
        "llm_judge_items": summary.get("llm_judge_items"),
        "llm_judge_model_used": summary.get("llm_judge_model_used"),
        "llm_judge_version_hash": summary.get("llm_judge_version_hash"),
        "llm_judge_self_consistency_n": summary.get("llm_judge_self_consistency_n"),
        "llm_judge_position_bias_enabled": summary.get("llm_judge_position_bias_enabled"),
        "llm_judge_error": summary.get("llm_judge_error"),
        "llm_judge_generation_avg": _coerce_float(summary.get("llm_judge_generation_avg")),
        "llm_judge_overall_avg": _coerce_float(summary.get("llm_judge_overall_avg")),
        "faithfulness_det": _coerce_float(summary.get("faithfulness_det")),
        "refusal_correctness": _coerce_float(summary.get("refusal_correctness")),
        "abstain_rate": _coerce_float(summary.get("abstain_rate")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build answer-quality summary from a regression run detail JSON.")
    parser.add_argument("--input", required=True, help="Regression run detail JSON path.")
    parser.add_argument("--out", default="artifacts/answer_quality.summary.json", help="Output summary JSON path.")
    args = parser.parse_args(argv)

    input_path = Path(str(args.input)).expanduser().resolve()
    out_path = Path(str(args.out)).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"input_not_found: {input_path}")

    payload = build_answer_quality_summary(_load_json(input_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[answer-quality-summary] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
