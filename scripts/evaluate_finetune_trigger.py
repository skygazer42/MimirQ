from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def evaluate_finetune_trigger(
    *,
    feedback_rows: list[dict[str, Any]],
    min_feedback: int,
    min_negative_feedback: int,
) -> dict[str, Any]:
    rows = [row for row in (feedback_rows or []) if isinstance(row, dict)]
    negative = [row for row in rows if int(row.get("rating") or 0) <= 2]

    request_ids: set[str] = set()
    for row in rows:
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        request_id = str(extra.get("retrieval_trace_request_id") or "").strip()
        if request_id:
            request_ids.add(request_id)

    reason_codes: list[str] = []
    if len(rows) < int(min_feedback):
        reason_codes.append("insufficient_feedback_total")
    if len(negative) < int(min_negative_feedback):
        reason_codes.append("insufficient_negative_feedback")
    if not reason_codes:
        reason_codes.append("thresholds_met")

    return {
        "schema": "mimirq.finetune_trigger_eval.v1",
        "summary": {
            "feedback_total": int(len(rows)),
            "negative_feedback_total": int(len(negative)),
            "unique_requests": int(len(request_ids)),
            "min_feedback": int(min_feedback),
            "min_negative_feedback": int(min_negative_feedback),
        },
        "should_trigger_finetune_eval": reason_codes == ["thresholds_met"],
        "reason_codes": reason_codes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate whether feedback volume is high enough to trigger finetune evaluation.")
    parser.add_argument("--feedback-json", required=True, help="Path to feedback JSON list.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--min-feedback", type=int, default=200, help="Minimum total feedback rows required.")
    parser.add_argument("--min-negative-feedback", type=int, default=50, help="Minimum negative feedback rows required.")
    args = parser.parse_args(argv)

    payload = evaluate_finetune_trigger(
        feedback_rows=_read_json(Path(args.feedback_json)),
        min_feedback=int(args.min_feedback),
        min_negative_feedback=int(args.min_negative_feedback),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
