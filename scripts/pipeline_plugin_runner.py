#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# This CLI runs local plugin checks/drafts, not the production API service.
warnings.filterwarnings(
    "ignore",
    message=r"SECRET_KEY is not configured\..*",
    category=UserWarning,
)

from app.rag.pipeline_plugins.local_runner import (  # noqa: E402
    build_pipeline_plugin_golden_draft_from_sample,
    run_pipeline_plugin_test,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test a MimirQ pipeline plugin package locally.")
    sub = parser.add_subparsers(dest="command", required=True)

    test = sub.add_parser("test", help="Run a local pipeline plugin test and write the test report.")
    test.add_argument("plugin_dir", help="Plugin package directory containing mimirq-plugin.json/yaml.")
    test.add_argument("--input", required=True, dest="input_path", help="JSON sample input: array or {documents:[...]}.")
    test.add_argument(
        "--stage",
        action="append",
        choices=["governance", "chunk", "kg"],
        dest="stages",
        help="Stage to test. Repeat for multiple stages. Defaults to every entry in the manifest.",
    )
    test.add_argument("--no-write-report", action="store_true", help="Run test without writing .mimirq-plugin-test.json.")

    golden = sub.add_parser("golden-draft", help="Build a local Golden regression bundle from a plugin sample.")
    golden.add_argument("plugin_dir", help="Plugin package directory containing mimirq-plugin.json/yaml.")
    golden.add_argument("--input", required=True, dest="input_path", help="JSON sample input: array or {documents:[...]}.")
    golden.add_argument(
        "--stage",
        action="append",
        choices=["governance", "chunk", "kg"],
        dest="stages",
        help="Stage to run. Defaults to governance then chunk when both exist; add kg to validate KG extraction too.",
    )
    golden.add_argument(
        "--dataset-id",
        default="00000000-0000-0000-0000-000000000000",
        help="Dataset id to embed in the regression bundle (default: %(default)s).",
    )
    golden.add_argument("--max-items", type=int, default=500, help="Maximum Golden cases to emit (default: %(default)s).")
    golden.add_argument("--out", default="-", help="Output JSON path, or '-' for stdout (default: %(default)s).")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "golden-draft":
        bundle = build_pipeline_plugin_golden_draft_from_sample(
            args.plugin_dir,
            input_path=args.input_path,
            dataset_id=UUID(str(args.dataset_id)),
            stages=args.stages,
            max_items=args.max_items,
        )
        text = json.dumps(bundle, ensure_ascii=False, indent=2)
        if str(args.out or "-") == "-":
            print(text)
        else:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        return 0

    if args.command != "test":
        return 2

    stages = args.stages
    if not stages:
        from app.rag.pipeline_plugins.registry import describe_plugin_dir  # noqa: PLC0415

        descriptor = describe_plugin_dir(Path(args.plugin_dir), require_test_report=False)
        stages = list(descriptor.entries)

    report = run_pipeline_plugin_test(
        args.plugin_dir,
        input_path=args.input_path,
        stages=stages,
        write_report=not args.no_write_report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
