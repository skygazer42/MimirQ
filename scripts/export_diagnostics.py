import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        payload = json.loads(text)
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _event_rows(metrics_rows: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [row for row in metrics_rows if str(row.get("event") or "") == event]


def _append_float(values: list[float], value: Any) -> None:
    try:
        values.append(float(value or 0.0))
    except Exception:
        return


def _summarize_metric_rows(
    metrics_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[float], list[float], Counter[str], Counter[str]]:
    rag_done = _event_rows(metrics_rows, "rag_done")
    rag_trace = _event_rows(metrics_rows, "rag_trace")
    elapsed_values: list[float] = []
    retrieval_elapsed_values: list[float] = []
    retrieval_mode_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    for row in rag_done:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        _append_float(elapsed_values, metrics.get("elapsed_sec"))
        _append_float(retrieval_elapsed_values, metrics.get("retrieval_elapsed_sec"))
        retrieval_mode = str(row.get("retrieval_mode") or metrics.get("retrieval_mode") or "").strip().lower()
        if retrieval_mode:
            retrieval_mode_counts[retrieval_mode] += 1
        route = str(row.get("route") or "").strip().lower()
        if route:
            route_counts[route] += 1
    return (
        rag_done,
        rag_trace,
        elapsed_values,
        retrieval_elapsed_values,
        retrieval_mode_counts,
        route_counts,
    )


def _summarize_feedback_rows(
    feedback_rows: list[dict[str, Any]],
) -> tuple[Counter[str], Counter[str], int]:
    rating_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    reason_present_count = 0
    for row in feedback_rows:
        rating = row.get("rating")
        if rating is not None:
            rating_counts[str(rating)] += 1
        if row.get("reason") not in (None, ""):
            reason_present_count += 1
        for tag in row.get("tags") or []:
            tag_s = str(tag or "").strip()
            if tag_s:
                tag_counts[tag_s] += 1
    return rating_counts, tag_counts, reason_present_count


def export_diagnostics(*, metrics_rows: list[dict[str, Any]], feedback_rows: list[dict[str, Any]]) -> dict[str, Any]:
    (
        rag_done,
        rag_trace,
        elapsed_values,
        retrieval_elapsed_values,
        retrieval_mode_counts,
        route_counts,
    ) = _summarize_metric_rows(metrics_rows)
    rating_counts, tag_counts, reason_present_count = _summarize_feedback_rows(feedback_rows)

    return {
        "schema": "mimirq.export_diagnostics.v1",
        "metrics": {
            "rag_done_count": len(rag_done),
            "rag_trace_count": len(rag_trace),
            "avg_elapsed_sec": _mean(elapsed_values),
            "avg_retrieval_elapsed_sec": _mean(retrieval_elapsed_values),
            "retrieval_mode_counts": dict(sorted(retrieval_mode_counts.items())),
            "route_counts": dict(sorted(route_counts.items())),
        },
        "feedback": {
            "total": len(feedback_rows),
            "rating_counts": dict(sorted(rating_counts.items())),
            "tag_counts": dict(sorted(tag_counts.items())),
            "reason_present_count": int(reason_present_count),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a redacted diagnostics summary from metrics and feedback artifacts."
    )
    parser.add_argument("--metrics-jsonl", required=True, help="Path to metrics JSONL file.")
    parser.add_argument("--feedback-json", required=True, help="Path to feedback JSON or JSONL file.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    args = parser.parse_args(argv)

    metrics_rows = _read_json_or_jsonl(Path(args.metrics_jsonl))
    feedback_rows = _read_json_or_jsonl(Path(args.feedback_json))
    payload = export_diagnostics(metrics_rows=metrics_rows, feedback_rows=feedback_rows)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
