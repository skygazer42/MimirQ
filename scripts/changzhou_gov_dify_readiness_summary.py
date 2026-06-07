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
    out = {
        "passed": bool(gate.get("passed")),
        "failed_conditions": gate.get("failed_conditions") if isinstance(gate.get("failed_conditions"), list) else [],
        "endpoint": _text(source.get("endpoint")),
        "endpoint_host": _text(source.get("endpoint_host")),
        "endpoint_host_is_local": bool(source.get("endpoint_host_is_local")),
        "endpoint_host_matches_local_machine": bool(source.get("endpoint_host_matches_local_machine")),
        "endpoint_host_is_loopback": bool(source.get("endpoint_host_is_loopback")),
        "external_api_name": _text(source.get("external_api_name")),
        "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
    }
    boundary = report.get("boundary") if isinstance(report.get("boundary"), dict) else {}
    if boundary:
        out["boundary"] = boundary
    return out


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


def _mimirq_direct_section(report: dict[str, Any]) -> dict[str, Any]:
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    failed_conditions: list[str] = []
    checks = gate.get("checks") if isinstance(gate.get("checks"), list) else []
    for check in checks:
        if not isinstance(check, dict) or check.get("passed") is True:
            continue
        metric = _text(check.get("metric")) or "quality_metric"
        failed_conditions.append(f"quality_gate_failed:{metric}")
    if not gate and not summary:
        failed_conditions.append("mimirq_direct_report_missing")
    out = {
        "passed": gate.get("passed") is True,
        "failed_conditions": failed_conditions,
        "summary": summary,
    }
    if source:
        out["source"] = source
    return out


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


def _overlay_stage_summary(section: dict[str, Any], stage_name: str, report: dict[str, Any]) -> None:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if not summary:
        return
    stages = section.setdefault("stages", {})
    if not isinstance(stages, dict):
        return
    stage = stages.get(stage_name) if isinstance(stages.get(stage_name), dict) else {}
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    stages[stage_name] = {
        "passed": gate.get("passed") if "passed" in gate else bool(stage.get("passed", True)),
        "summary": summary,
    }


def _trace_warning_cases(report: dict[str, Any]) -> dict[str, list[str]]:
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    warning_cases: dict[str, list[str]] = {}
    for item in cases:
        if not isinstance(item, dict):
            continue
        case_id = _text(item.get("id") or item.get("case_id"))
        if not case_id:
            continue
        checks = {
            "trace.node_route_mismatch": item.get("node_route_matched") is False,
            "trace.route_compensated": item.get("route_compensated") is True,
            "trace.route_mismatch": item.get("route_matched") is False,
            "trace.region_mismatch": item.get("region_matched") is False,
            "trace.fallback": item.get("fallback") is True,
        }
        for key, matched in checks.items():
            if matched:
                warning_cases.setdefault(key, []).append(case_id)
    return warning_cases


def _eval_warning_cases(report: dict[str, Any]) -> dict[str, list[str]]:
    results = report.get("results") if isinstance(report.get("results"), list) else []
    warning_cases: dict[str, list[str]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        case_id = _text(item.get("id") or item.get("case_id"))
        if not case_id:
            continue
        quality = item.get("generated_answer_quality")
        if not isinstance(quality, dict) or quality.get("provided") is not True:
            continue
        if quality.get("grounded") is False:
            warning_cases.setdefault("eval.generated_answer_missing", []).append(case_id)
        if quality.get("policy_clean") is False:
            warning_cases.setdefault("eval.generated_answer_policy_violation", []).append(case_id)
        if quality.get("fallback") is True:
            warning_cases.setdefault("eval.generated_answer_fallback", []).append(case_id)
    return warning_cases


def _region_extractor_empty(item: dict[str, Any]) -> bool:
    regions = item.get("regions") if isinstance(item.get("regions"), list) else []
    for region in regions:
        if isinstance(region, dict):
            area = _text(region.get("area") or region.get("region"))
            if region.get("__is_success") == 0 or not area:
                return True
            continue
        if _text(region) == "未知":
            return True
    return False


def _append_unique(out: list[str], value: str) -> None:
    clean = _text(value)
    if clean and clean not in out:
        out.append(clean)


def _empty_marker(value: Any) -> str:
    text = _text(value)
    return text if text else "<empty>"


def _region_extractor_detail_texts(item: dict[str, Any]) -> list[str]:
    details: list[str] = []
    extractors = item.get("region_extractors") if isinstance(item.get("region_extractors"), list) else []
    for extractor in extractors:
        if not isinstance(extractor, dict):
            continue
        title = _text(extractor.get("title")) or "区域提取器"
        if "region" in extractor:
            region = _empty_marker(extractor.get("region"))
            if region == "未知" or region == "<empty>":
                _append_unique(details, f"{title}: region={region}")
        reason = _text(extractor.get("reason"))
        if reason:
            _append_unique(details, f"{title}: {reason}")
        if "area" in extractor and not _text(extractor.get("area")):
            _append_unique(details, f"{title}: area=<empty>")
    if details:
        return details

    regions = item.get("regions") if isinstance(item.get("regions"), list) else []
    for region in regions:
        if isinstance(region, dict):
            reason = _text(region.get("__reason"))
            if reason:
                _append_unique(details, f"区域提取器: {reason}")
            for key in ("region", "area"):
                if key in region:
                    value = _empty_marker(region.get(key))
                    if value == "未知" or value == "<empty>":
                        _append_unique(details, f"区域提取器: {key}={value}")
            continue
        if _text(region) == "未知":
            _append_unique(details, "区域提取器: region=未知")
    return details


def _trace_warning_diagnoses(report: dict[str, Any]) -> dict[str, list[str]]:
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    diagnoses: dict[str, list[str]] = {}
    for item in cases:
        if not isinstance(item, dict):
            continue
        case_id = _text(item.get("id") or item.get("case_id"))
        if not case_id:
            continue
        if item.get("route_compensated") is True:
            diagnoses.setdefault("route_compensated_by_retrieval_evidence", []).append(case_id)
        if item.get("region_matched") is False:
            if _region_extractor_empty(item):
                diagnoses.setdefault("dify_area_extractor_empty", []).append(case_id)
            else:
                diagnoses.setdefault("region_mismatch", []).append(case_id)
        if item.get("route_matched") is False:
            diagnoses.setdefault("route_mismatch", []).append(case_id)
        if item.get("fallback") is True:
            diagnoses.setdefault("fallback", []).append(case_id)
    return diagnoses


def _trace_warning_diagnosis_details(report: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    details: dict[str, dict[str, list[str]]] = {}
    for item in cases:
        if not isinstance(item, dict):
            continue
        case_id = _text(item.get("id") or item.get("case_id"))
        if not case_id:
            continue
        if item.get("region_matched") is False and _region_extractor_empty(item):
            case_details = _region_extractor_detail_texts(item)
            if case_details:
                details.setdefault("dify_area_extractor_empty", {})[case_id] = case_details
    return details


def _eval_warning_diagnosis_details(report: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    results = report.get("results") if isinstance(report.get("results"), list) else []
    details: dict[str, dict[str, list[str]]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        case_id = _text(item.get("id") or item.get("case_id"))
        if not case_id:
            continue
        quality = item.get("generated_answer_quality")
        if not isinstance(quality, dict) or quality.get("provided") is not True:
            continue
        if quality.get("grounded") is False:
            case_details = ["grounded=false"]
            missing_key_points = [
                _text(value)
                for value in quality.get("missing_key_points", [])
                if _text(value)
            ] if isinstance(quality.get("missing_key_points"), list) else []
            if missing_key_points:
                case_details.append(f"missing_key_points={','.join(missing_key_points)}")
            details.setdefault("eval.generated_answer_missing", {})[case_id] = case_details
        if quality.get("policy_clean") is False:
            forbidden_phrases = [
                _text(value)
                for value in quality.get("forbidden_phrases", [])
                if _text(value)
            ] if isinstance(quality.get("forbidden_phrases"), list) else []
            case_details = ["policy_clean=false"]
            if forbidden_phrases:
                case_details = [f"forbidden_phrases={','.join(forbidden_phrases)}"]
            details.setdefault("eval.generated_answer_policy_violation", {})[case_id] = case_details
        if quality.get("fallback") is True:
            details.setdefault("eval.generated_answer_fallback", {})[case_id] = ["fallback=true"]
    return details


def _merge_case_map(*maps: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for item_map in maps:
        for key, values in item_map.items():
            for value in values:
                _append_unique(merged.setdefault(key, []), value)
    return merged


def _merge_detail_map(*maps: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    merged: dict[str, dict[str, list[str]]] = {}
    for item_map in maps:
        for key, cases in item_map.items():
            for case_id, values in cases.items():
                target_values = merged.setdefault(key, {}).setdefault(case_id, [])
                for value in values:
                    _append_unique(target_values, value)
    return merged


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


def _next_action(stage: str, reason: str) -> str:
    if not stage:
        return ""
    if stage == "console_auth":
        return (
            "Refresh Dify console login with DIFY_CONSOLE_EMAIL and DIFY_CONSOLE_PASSWORD_FILE, "
            "then run make dify-console-login."
        )
    if stage == "knowledge_map":
        return "Run make changzhou-dify-knowledge-map-check and fix DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON."
    if stage == "mimirq_direct":
        return "Run make changzhou-dify-mimirq-direct-gate and inspect /tmp/changzhou_gov_dify_mimirq_direct_gate.json."
    if stage == "external_probe":
        if reason in {"endpoint_missing", "endpoint_host_is_loopback"}:
            return "Set Dify external knowledge endpoint to a MimirQ URL reachable from the Dify server, not localhost."
        return "Run make changzhou-dify-external-probe and inspect /tmp/changzhou_gov_dify_external_probe.json."
    if stage == "full_gate":
        return "Run make changzhou-dify-full-gate and inspect the failed stage artifact under CHANGZHOU_DIFY_OUT_PREFIX."
    return "Inspect the readiness artifact for the failed stage."


def build_readiness_summary(
    *,
    knowledge_map: dict[str, Any] | None = None,
    mimirq_direct: dict[str, Any] | None = None,
    console_auth: dict[str, Any] | None = None,
    external_probe: dict[str, Any],
    full_gate_summary: dict[str, Any],
    artifacts: dict[str, str],
    generated_at: str = "",
    artifact_reports: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    knowledge_section = _knowledge_map_section(knowledge_map or {}) if knowledge_map is not None else None
    mimirq_section = _mimirq_direct_section(mimirq_direct or {}) if mimirq_direct is not None else None
    console_section = _console_auth_section(console_auth or {}) if console_auth is not None else None
    external_section = _external_probe_section(external_probe)
    full_section = _full_gate_section(full_gate_summary)
    eval_report = (artifact_reports or {}).get("eval", {})
    trace_report = (artifact_reports or {}).get("trace", {})
    if isinstance(eval_report, dict):
        _overlay_stage_summary(full_section, "eval", eval_report)
    if isinstance(trace_report, dict):
        warning_diagnoses = _trace_warning_diagnoses(trace_report)
        if warning_diagnoses:
            full_section["warning_diagnoses"] = warning_diagnoses
    warning_case_maps: list[dict[str, list[str]]] = []
    warning_detail_maps: list[dict[str, dict[str, list[str]]]] = []
    if isinstance(eval_report, dict):
        warning_case_maps.append(_eval_warning_cases(eval_report))
        warning_detail_maps.append(_eval_warning_diagnosis_details(eval_report))
    if isinstance(trace_report, dict):
        warning_case_maps.append(_trace_warning_cases(trace_report))
        warning_detail_maps.append(_trace_warning_diagnosis_details(trace_report))
    warning_cases = _merge_case_map(*warning_case_maps)
    if warning_cases:
        full_section["warning_cases"] = warning_cases
    warning_diagnosis_details = _merge_detail_map(*warning_detail_maps)
    if warning_diagnosis_details:
        full_section["warning_diagnosis_details"] = warning_diagnosis_details
    staged_sections: list[tuple[str, dict[str, Any]]] = []
    if knowledge_section is not None:
        staged_sections.append(("knowledge_map", knowledge_section))
    if mimirq_section is not None:
        staged_sections.append(("mimirq_direct", mimirq_section))
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
    next_action = _next_action(root_cause_stage, root_cause_reason)
    report = {
        "schema": SCHEMA,
        "generated_at": _text(generated_at) or _utc_now_text(),
        "summary": {
            "passed": not failed_stages,
            "failed_stages": failed_stages,
            "skipped_stages": skipped_stages,
            "stage_count": len(staged_sections),
            "root_cause_stage": root_cause_stage,
            "root_cause_reason": root_cause_reason,
            "next_action": next_action,
        },
        "artifacts": _clean_artifacts(artifacts),
    }
    if knowledge_section is not None:
        report["knowledge_map"] = sections_by_stage["knowledge_map"]
    if mimirq_section is not None:
        report["mimirq_direct"] = sections_by_stage["mimirq_direct"]
    if console_section is not None:
        report["console_auth"] = sections_by_stage["console_auth"]
    report["external_probe"] = sections_by_stage["external_probe"]
    report["full_gate"] = sections_by_stage["full_gate"]
    generated_by_artifact = _artifact_generated_at(
        artifact_reports
        or {
            "knowledge_map": knowledge_map or {},
            "mimirq_direct": mimirq_direct or {},
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
    parser.add_argument("--mimirq-direct", default="")
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
        "mimirq_direct": str(args.mimirq_direct),
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
        mimirq_direct=artifact_reports.get("mimirq_direct") if _text(args.mimirq_direct) else None,
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
