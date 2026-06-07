#!/usr/bin/env python3
"""Print a compact human-readable Changzhou Dify readiness status."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _load_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _parse_timestamp(value: str) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_line(generated_at: str, *, now: datetime, max_age_minutes: int) -> str:
    parsed = _parse_timestamp(generated_at)
    if parsed is None:
        return "Freshness: unknown (invalid generated_at)"
    age_seconds = max(0, int((now.astimezone(timezone.utc) - parsed).total_seconds()))
    age_minutes = age_seconds // 60
    if age_seconds > max_age_minutes * 60:
        return f"Freshness: STALE (age={age_minutes}m, max={max_age_minutes}m)"
    return f"Freshness: fresh (age={age_minutes}m, max={max_age_minutes}m)"


def format_status(
    report: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_minutes: int | None = 30,
) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
    artifact_times = report.get("artifact_generated_at") if isinstance(report.get("artifact_generated_at"), dict) else {}
    passed = summary.get("passed") is True
    lines = [f"Changzhou Dify readiness: {'PASSED' if passed else 'FAILED'}"]
    generated_at = _text(report.get("generated_at"))
    if generated_at:
        lines.append(f"Generated at: {generated_at}")
    if max_age_minutes and max_age_minutes > 0:
        if generated_at:
            lines.append(_freshness_line(generated_at, now=now or datetime.now(timezone.utc), max_age_minutes=max_age_minutes))
        else:
            lines.append("Freshness: unknown (missing generated_at)")
    if not passed:
        root_stage = _text(summary.get("root_cause_stage")) or ",".join(_text_list(summary.get("failed_stages")))
        root_reason = _text(summary.get("root_cause_reason"))
        if root_stage or root_reason:
            lines.append(f"Root cause: {root_stage}{f' ({root_reason})' if root_reason else ''}")
        next_action = _text(summary.get("next_action"))
        if next_action:
            lines.append(f"Next action: {next_action}")
    skipped = _text_list(summary.get("skipped_stages"))
    if skipped:
        lines.append(f"Skipped stages: {', '.join(skipped)}")
    if artifact_times:
        time_items = [f"{key}={value}" for key, value in artifact_times.items() if _text(value)]
        if time_items:
            lines.append(f"Artifact times: {'; '.join(time_items)}")
    if artifacts:
        artifact_items = [f"{key}={value}" for key, value in artifacts.items() if _text(value)]
        if artifact_items:
            lines.append(f"Artifacts: {'; '.join(artifact_items)}")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print compact Changzhou Dify readiness status.")
    parser.add_argument("--summary", required=True, help="Readiness summary JSON path.")
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=30,
        help="Warn when the summary generated_at is older than this many minutes. Use 0 to disable.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = _load_json(str(args.summary))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Changzhou Dify readiness: UNKNOWN\nRoot cause: summary_read_error ({exc})", file=sys.stderr)
        return 2
    text = format_status(report, max_age_minutes=args.max_age_minutes)
    print(text)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return 0 if summary.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
