#!/usr/bin/env python3
"""Build a compact readiness summary from Changzhou Dify gate artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "mimirq.changzhou_gov_service_knowledge.dify_readiness_summary.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean_artifacts(artifacts: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in artifacts.items() if _text(value)}


def _external_probe_section(report: dict[str, Any]) -> dict[str, Any]:
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    return {
        "passed": bool(gate.get("passed")),
        "failed_conditions": gate.get("failed_conditions") if isinstance(gate.get("failed_conditions"), list) else [],
        "endpoint": _text(source.get("endpoint")),
        "endpoint_host": _text(source.get("endpoint_host")),
        "endpoint_host_is_local": bool(source.get("endpoint_host_is_local")),
        "external_api_name": _text(source.get("external_api_name")),
        "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
    }


def _full_gate_section(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    stages: dict[str, Any] = {}
    for name, stage in (report.get("stages") or {}).items():
        if not isinstance(stage, dict):
            continue
        stages[_text(name)] = {
            "passed": bool(stage.get("passed")),
            "summary": stage.get("summary") if isinstance(stage.get("summary"), dict) else {},
        }
    return {
        "passed": bool(summary.get("passed")),
        "failed_stages": summary.get("failed_stages") if isinstance(summary.get("failed_stages"), list) else [],
        "summary": summary,
        "stages": stages,
    }


def build_readiness_summary(
    *,
    external_probe: dict[str, Any],
    full_gate_summary: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any]:
    external_section = _external_probe_section(external_probe)
    full_section = _full_gate_section(full_gate_summary)
    failed_stages: list[str] = []
    if external_section["passed"] is not True:
        failed_stages.append("external_probe")
    if full_section["passed"] is not True:
        failed_stages.append("full_gate")
    return {
        "schema": SCHEMA,
        "summary": {
            "passed": not failed_stages,
            "failed_stages": failed_stages,
            "stage_count": 2,
        },
        "artifacts": _clean_artifacts(artifacts),
        "external_probe": external_section,
        "full_gate": full_section,
    }


def _load_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a compact Changzhou Dify readiness summary.")
    parser.add_argument("--external-probe", required=True)
    parser.add_argument("--full-summary", required=True)
    parser.add_argument("--answers", default="")
    parser.add_argument("--eval", default="")
    parser.add_argument("--trace", default="")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_readiness_summary(
        external_probe=_load_json(str(args.external_probe)),
        full_gate_summary=_load_json(str(args.full_summary)),
        artifacts={
            "external_probe": str(args.external_probe),
            "full_gate": str(args.full_summary),
            "answers": str(args.answers),
            "eval": str(args.eval),
            "trace": str(args.trace),
        },
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if bool((report.get("summary") or {}).get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
