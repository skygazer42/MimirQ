#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.changzhou_gov_plugin_chunk_evidence import _load_json, _markdown_table, _text, _write_text  # noqa: E402

SCHEMA = "mimirq.changzhou_gov.plugin_test_evidence.v1"
DEFAULT_INPUT = "/tmp/changzhou_gov_plugin_test_report.json"
DEFAULT_JSON_OUT = "/tmp/changzhou_gov_plugin_test_evidence.json"
DEFAULT_MARKDOWN_OUT = "/tmp/changzhou_gov_plugin_test_evidence.md"
REQUIRED_STAGES = ("governance", "chunk", "kg")


def _stage_summary(report: dict[str, Any]) -> tuple[dict[str, bool], list[str], list[str]]:
    raw_stages = report.get("stages") if isinstance(report.get("stages"), dict) else {}
    stages: dict[str, bool] = {}
    failed: list[str] = []
    for name, value in sorted(raw_stages.items()):
        passed = isinstance(value, dict) and value.get("passed") is True
        stages[str(name)] = passed
        if not passed:
            failed.append(str(name))
    missing = [stage for stage in REQUIRED_STAGES if stage not in stages]
    return stages, failed, missing


def build_evidence(raw_report_path: str | Path = DEFAULT_INPUT) -> dict[str, Any]:
    report = _load_json(raw_report_path)
    stages, failed_stages, missing_stages = _stage_summary(report)
    golden_draft = report.get("golden_draft") if isinstance(report.get("golden_draft"), dict) else {}
    golden_passed = golden_draft.get("passed") is True
    passed = report.get("passed") is True and golden_passed and not failed_stages and not missing_stages
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_report": str(raw_report_path),
        "passed": passed,
        "stage_count": len(stages),
        "stages": stages,
        "failed_stages": failed_stages,
        "missing_stages": missing_stages,
        "golden_draft": {
            "passed": golden_passed,
            "items_total": int(golden_draft.get("items_total") or 0),
        },
    }


def format_markdown(evidence: dict[str, Any]) -> str:
    golden = evidence.get("golden_draft") if isinstance(evidence.get("golden_draft"), dict) else {}
    stages = evidence.get("stages") if isinstance(evidence.get("stages"), dict) else {}
    lines = [
        "# Changzhou Gov Plugin Test Evidence",
        "",
        f"**Status:** {'PASSED' if evidence.get('passed') is True else 'FAILED'}",
        f"**Generated at:** {_text(evidence.get('generated_at'))}",
        "",
        "## Summary",
        "",
        *_markdown_table(
            ["passed", "stage_count", "failed_stages", "missing_stages", "golden_draft_passed", "golden_draft_items"],
            [
                [
                    _text(evidence.get("passed")),
                    _text(evidence.get("stage_count")),
                    ", ".join(evidence.get("failed_stages") or []),
                    ", ".join(evidence.get("missing_stages") or []),
                    _text(golden.get("passed")),
                    _text(golden.get("items_total")),
                ]
            ],
        ),
        "",
        "## Stage Matrix",
        "",
        *_markdown_table(["Stage", "Passed"], [[name, _text(passed)] for name, passed in sorted(stages.items())]),
        "",
        "## Safety",
        "",
        "This evidence file intentionally omits Golden draft sample questions and raw plugin test details.",
    ]
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build shareable Changzhou plugin test evidence from a local raw report."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--json-out", default=DEFAULT_JSON_OUT)
    parser.add_argument("--markdown-out", default=DEFAULT_MARKDOWN_OUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        evidence = build_evidence(args.input)
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-gov-plugin-test-evidence] ERROR: {exc}", file=sys.stderr)
        return 2
    json_text = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if _text(args.json_out) == "-":
        print(json_text, end="")
    else:
        _write_text(args.json_out, json_text)
    if _text(args.markdown_out):
        _write_text(args.markdown_out, format_markdown(evidence))
    return 0 if evidence.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
