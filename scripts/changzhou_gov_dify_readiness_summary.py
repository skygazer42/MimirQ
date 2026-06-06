#!/usr/bin/env python3
"""Build a compact readiness summary from Changzhou Dify gate artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "mimirq.changzhou_gov_service_knowledge.dify_readiness_summary.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean_artifacts(artifacts: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in artifacts.items() if _text(value)}


def _artifact_generated_at(artifact_reports: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        key: _text(report.get("generated_at"))
        for key, report in artifact_reports.items()
        if isinstance(report, dict) and _text(report.get("generated_at"))
    }


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _knowledge_map_section(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return {
        "passed": bool(summary.get("passed")),
        "failed_conditions": summary.get("failed_conditions") if isinstance(summary.get("failed_conditions"), list) else [],
        "summary": summary,
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
    knowledge_map: dict[str, Any] | None = None,
    external_probe: dict[str, Any],
    full_gate_summary: dict[str, Any],
    artifacts: dict[str, str],
    generated_at: str = "",
    artifact_reports: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    knowledge_section = _knowledge_map_section(knowledge_map or {}) if knowledge_map is not None else None
    external_section = _external_probe_section(external_probe)
    full_section = _full_gate_section(full_gate_summary)
    failed_stages: list[str] = []
    if knowledge_section is not None and knowledge_section["passed"] is not True:
        failed_stages.append("knowledge_map")
    if external_section["passed"] is not True:
        failed_stages.append("external_probe")
    if full_section["passed"] is not True:
        failed_stages.append("full_gate")
    report = {
        "schema": SCHEMA,
        "generated_at": _text(generated_at) or _utc_now_text(),
        "summary": {
            "passed": not failed_stages,
            "failed_stages": failed_stages,
            "stage_count": 3 if knowledge_section is not None else 2,
        },
        "artifacts": _clean_artifacts(artifacts),
    }
    if knowledge_section is not None:
        report["knowledge_map"] = knowledge_section
    report["external_probe"] = external_section
    report["full_gate"] = full_section
    generated_by_artifact = _artifact_generated_at(
        artifact_reports
        or {
            "knowledge_map": knowledge_map or {},
            "external_probe": external_probe,
            "full_gate": full_gate_summary,
        }
    )
    if generated_by_artifact:
        report["artifact_generated_at"] = generated_by_artifact
    return report


def _load_json(path: str) -> dict[str, Any]:
    if not Path(path).is_file():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a compact Changzhou Dify readiness summary.")
    parser.add_argument("--knowledge-map", default="")
    parser.add_argument("--external-probe", required=True)
    parser.add_argument("--full-summary", required=True)
    parser.add_argument("--answers", default="")
    parser.add_argument("--eval", default="")
    parser.add_argument("--trace", default="")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    artifact_paths = {
        "knowledge_map": str(args.knowledge_map),
        "external_probe": str(args.external_probe),
        "full_gate": str(args.full_summary),
        "answers": str(args.answers),
        "eval": str(args.eval),
        "trace": str(args.trace),
    }
    artifact_reports = {key: _load_json(path) for key, path in artifact_paths.items() if _text(path)}
    report = build_readiness_summary(
        knowledge_map=artifact_reports.get("knowledge_map") if _text(args.knowledge_map) else None,
        external_probe=artifact_reports.get("external_probe", {}),
        full_gate_summary=artifact_reports.get("full_gate", {}),
        artifacts=artifact_paths,
        artifact_reports=artifact_reports,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if bool((report.get("summary") or {}).get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
