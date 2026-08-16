#!/usr/bin/env python3


import argparse
import json
from pathlib import Path
from typing import Any

from app.rag.evaluation.judge_calibration import build_calibration_report


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate unified LLM judge calibration against human labels.")
    parser.add_argument("--input", required=True, help="Human-reviewed calibration JSON.")
    parser.add_argument("--out", default="artifacts/llm_judge_calibration.report.json")
    parser.add_argument("--min-items", type=int, default=50)
    parser.add_argument("--min-kappa", type=float, default=0.6)
    args = parser.parse_args(argv)

    input_path = Path(str(args.input)).expanduser().resolve()
    out_path = Path(str(args.out)).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"input_not_found:{input_path}")

    try:
        report = build_calibration_report(
            _load_json(input_path),
            min_items=max(1, int(args.min_items)),
            min_kappa=float(args.min_kappa),
        )
    except ValueError as exc:
        report = {
            "schema": "mimirq.llm_judge_calibration_report.v1",
            "passed": False,
            "error": str(exc),
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[llm-judge-calibration] wrote {out_path}")
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
