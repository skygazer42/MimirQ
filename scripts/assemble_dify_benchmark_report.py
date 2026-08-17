#!/usr/bin/env python3
"""Assemble a unified Dify/MimirQ benchmark report from separately produced run files."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _case_id(item: dict[str, Any]) -> str:
    return _text(item.get("case_id") or item.get("id"))


def _item_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (_case_id(item), _text(item.get("system")))


def _failure_reasons(items: list[dict[str, Any]]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for item in items:
        if item.get("ok") is True:
            continue
        reason = _text(item.get("error")) or "unknown"
        if "timed out" in reason.lower():
            reason = "timed_out"
        elif reason.startswith("HTTP "):
            reason = reason.split(":", 1)[0]
        reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _load_run_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def merge_run_payloads(payloads: list[dict[str, Any]], *, run_name: str) -> dict[str, Any]:
    if not payloads:
        raise ValueError(f"no payloads to merge for {run_name}")

    merged_items: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            case_id = _case_id(item)
            if case_id:
                merged_items[case_id] = dict(item)

    latest = dict(payloads[-1])
    ordered_items = sorted(merged_items.values(), key=_item_sort_key)
    declared_cases = max(
        [
            int((payload.get("summary") or {}).get("cases") or 0)
            for payload in payloads
            if isinstance(payload.get("summary"), dict)
        ]
        or [0]
    )
    total_cases = max(declared_cases, len(ordered_items))
    succeeded = sum(1 for item in ordered_items if item.get("ok") is True)
    merged = dict(latest)
    merged["items"] = ordered_items
    merged["summary"] = {
        "cases": total_cases,
        "succeeded": succeeded,
        "failed": len(ordered_items) - succeeded,
        "pending": max(0, total_cases - len(ordered_items)),
        "partial": len(ordered_items) < total_cases,
        "failure_reasons": _failure_reasons(ordered_items),
        "merged_sources": len(payloads),
    }
    return merged


def collect_merged_runs(source_dirs: list[str]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw_dir in source_dirs:
        source_dir = Path(raw_dir)
        if not source_dir.is_dir():
            print(f"[assemble-dify-benchmark-report] WARN: missing source dir {source_dir}", file=sys.stderr)
            continue
        for run_file in sorted(source_dir.glob("run_*.json")):
            payload = _load_run_payload(run_file)
            if payload is None:
                print(f"[assemble-dify-benchmark-report] WARN: unreadable run file {run_file}", file=sys.stderr)
                continue
            grouped.setdefault(run_file.name, []).append(payload)

    return {run_name: merge_run_payloads(payloads, run_name=run_name) for run_name, payloads in sorted(grouped.items())}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect run_*.json files from multiple benchmark directories and rebuild a single comparison report."
    )
    parser.add_argument("--cases", required=True, help="Path to the shared benchmark cases JSON")
    parser.add_argument("--out-dir", required=True, help="Destination directory for the assembled report")
    parser.add_argument(
        "--app-key-file", default="", help="Optional app key file passed through to report-only rebuild"
    )
    parser.add_argument("--include-mimirq-direct", action="store_true")
    parser.add_argument(
        "--source-dir",
        action="append",
        default=[],
        help="Source directory containing one or more run_*.json files. Repeat as needed.",
    )
    parser.add_argument(
        "--app",
        action="append",
        default=[],
        help="Forwarded --app argument for scripts/dify_3way_benchmark.py report-only rebuild.",
    )
    parser.add_argument("--write-bundle", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    merged_runs = collect_merged_runs(args.source_dir)

    if not merged_runs:
        print("[assemble-dify-benchmark-report] ERROR: no run_*.json files found in source dirs", file=sys.stderr)
        return 2

    copied = 0
    for run_name, payload in merged_runs.items():
        destination = out_dir / run_name
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        copied += 1

    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "dify_3way_benchmark.py"),
        "--prebuilt-cases",
        str(args.cases),
        "--out-dir",
        str(out_dir),
        "--report-only",
    ]
    if _text(args.app_key_file):
        command.extend(["--app-key-file", str(args.app_key_file)])
    if args.include_mimirq_direct:
        command.append("--include-mimirq-direct")
    if args.write_bundle:
        command.append("--write-bundle")
    for app_arg in args.app:
        command.extend(["--app", str(app_arg)])

    print("[assemble-dify-benchmark-report] copied_runs=", copied)
    print("[assemble-dify-benchmark-report] rebuild_command=", " ".join(command))
    return subprocess.call(command, cwd=REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
