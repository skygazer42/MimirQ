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


def _console_auth_section(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": report.get("valid") is True,
        "reason": _text(report.get("reason")),
        "ttl_seconds": report.get("ttl_seconds"),
        "min_ttl_seconds": report.get("min_ttl_seconds"),
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


def _with_status(section: dict[str, Any], *, blocker: str) -> dict[str, Any]:
    if blocker:
        return {"passed": False, "status": "skipped", "blocked_by": blocker}
    out = dict(section)
    out["status"] = "passed" if section.get("passed") is True else "failed"
    return out


def _root_cause_reason(stage: str, section: dict[str, Any]) -> str:
    if stage == "console_auth":
        return _text(section.get("reason")) or "console_auth_failed"
    conditions = section.get("failed_conditions")
    if isinstance(conditions, list) and conditions:
        return _text(conditions[0]) or f"{stage}_failed"
    summary = section.get("summary") if isinstance(section.get("summary"), dict) else {}
    summary_conditions = summary.get("failed_conditions")
    if isinstance(summary_conditions, list) and summary_conditions:
        return _text(summary_conditions[0]) or f"{stage}_failed"
    failed = section.get("failed_stages")
    if isinstance(failed, list) and failed:
        return f"{stage}:{_text(failed[0])}"
    if stage == "knowledge_map":
        return "missing_or_invalid_knowledge_map"
    return f"{stage}_failed"


def build_readiness_summary(
    *,
    knowledge_map: dict[str, Any] | None = None,
    console_auth: dict[str, Any] | None = None,
    external_probe: dict[str, Any],
    full_gate_summary: dict[str, Any],
    artifacts: dict[str, str],
    generated_at: str = "",
    artifact_reports: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    knowledge_section = _knowledge_map_section(knowledge_map or {}) if knowledge_map is not None else None
    console_section = _console_auth_section(console_auth or {}) if console_auth is not None else None
    external_section = _external_probe_section(external_probe)
    full_section = _full_gate_section(full_gate_summary)
    staged_sections: list[tuple[str, dict[str, Any]]] = []
    if knowledge_section is not None:
        staged_sections.append(("knowledge_map", knowledge_section))
    if console_section is not None:
        staged_sections.append(("console_auth", console_section))
    staged_sections.extend((("external_probe", external_section), ("full_gate", full_section)))

    blocker = ""
    failed_stages: list[str] = []
    skipped_stages: list[str] = []
    sections_by_stage: dict[str, dict[str, Any]] = {}
    for stage, section in staged_sections:
        with_status = _with_status(section, blocker=blocker)
        sections_by_stage[stage] = with_status
        if with_status["status"] == "skipped":
            skipped_stages.append(stage)
            continue
        if with_status["status"] == "failed":
            failed_stages.append(stage)
            blocker = stage
    root_cause_stage = failed_stages[0] if failed_stages else ""
    root_cause_reason = _root_cause_reason(root_cause_stage, sections_by_stage[root_cause_stage]) if root_cause_stage else ""
    report = {
        "schema": SCHEMA,
        "generated_at": _text(generated_at) or _utc_now_text(),
        "summary": {
            "passed": not failed_stages,
            "failed_stages": failed_stages,
            "skipped_stages": skipped_stages,
            "stage_count": 2 + int(knowledge_section is not None) + int(console_section is not None),
            "root_cause_stage": root_cause_stage,
            "root_cause_reason": root_cause_reason,
        },
        "artifacts": _clean_artifacts(artifacts),
    }
    if knowledge_section is not None:
        report["knowledge_map"] = sections_by_stage["knowledge_map"]
    if console_section is not None:
        report["console_auth"] = sections_by_stage["console_auth"]
    report["external_probe"] = sections_by_stage["external_probe"]
    report["full_gate"] = sections_by_stage["full_gate"]
    generated_by_artifact = _artifact_generated_at(
        artifact_reports
        or {
            "knowledge_map": knowledge_map or {},
            "console_auth": console_auth or {},
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
    parser.add_argument("--console-auth", default="")
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
        "console_auth": str(args.console_auth),
        "external_probe": str(args.external_probe),
        "full_gate": str(args.full_summary),
        "answers": str(args.answers),
        "eval": str(args.eval),
        "trace": str(args.trace),
    }
    artifact_reports = {key: _load_json(path) for key, path in artifact_paths.items() if _text(path)}
    report = build_readiness_summary(
        knowledge_map=artifact_reports.get("knowledge_map") if _text(args.knowledge_map) else None,
        console_auth=artifact_reports.get("console_auth") if _text(args.console_auth) else None,
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
