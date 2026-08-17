#!/usr/bin/env python3
"""Print a compact human-readable Changzhou Dify readiness status."""

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


def _join_url(base_url: str, *parts: str) -> str:
    base = _text(base_url).rstrip("/")
    if not base:
        return ""
    suffix = "/".join(_text(part).strip("/") for part in parts if _text(part).strip("/"))
    return f"{base}/{suffix}" if suffix else base


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


def _stages_with_status(report: dict[str, Any], status: str) -> list[str]:
    stages = ("knowledge_map", "mimirq_direct", "kg_compare", "console_auth", "external_probe", "full_gate")
    out: list[str] = []
    for stage in stages:
        section = report.get(stage)
        if isinstance(section, dict) and _text(section.get("status")) == status:
            out.append(stage)
    return out


def _nonzero_metric(summary: dict[str, Any], metric: str) -> str:
    value = summary.get(metric)
    if not isinstance(value, int | float) or value == 0:
        return ""
    return f"{metric}={value}"


def _full_gate_warning_items(report: dict[str, Any]) -> list[str]:
    full_gate = report.get("full_gate") if isinstance(report.get("full_gate"), dict) else {}
    stages = full_gate.get("stages") if isinstance(full_gate.get("stages"), dict) else {}
    watched_metrics = {
        "preflight": ("area_route_warnings", "case_input_violations"),
        "eval": (
            "generated_answer_missing_cases",
            "generated_answer_fallback_cases",
        ),
        "trace": (
            "node_route_mismatch_cases",
            "route_compensated_cases",
            "route_mismatch_cases",
            "region_mismatch_cases",
            "fallback_cases",
            "empty_retrieval_cases",
            "trace_errors",
        ),
    }
    out: list[str] = []
    covered_case_keys: set[str] = set()
    for stage, metrics in watched_metrics.items():
        section = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
        stage_summary = section.get("summary") if isinstance(section.get("summary"), dict) else {}
        for metric in metrics:
            item = _nonzero_metric(stage_summary, metric)
            if item:
                out.append(f"{stage}.{item}")
                suffix = "_cases" if metric.endswith("_cases") else ""
                metric_base = metric[: -len(suffix)] if suffix else metric
                covered_case_keys.add(f"{stage}.{metric_base}")
    warning_cases = full_gate.get("warning_cases") if isinstance(full_gate.get("warning_cases"), dict) else {}
    for key, value in warning_cases.items():
        clean_key = _text(key)
        if not clean_key or clean_key in covered_case_keys or not isinstance(value, list):
            continue
        case_count = len([item for item in value if _text(item)])
        if case_count:
            out.append(f"{clean_key}_cases={case_count}")
    return out


def _full_gate_warning_case_items(report: dict[str, Any]) -> list[str]:
    full_gate = report.get("full_gate") if isinstance(report.get("full_gate"), dict) else {}
    warning_cases = full_gate.get("warning_cases") if isinstance(full_gate.get("warning_cases"), dict) else {}
    out: list[str] = []
    for key, value in warning_cases.items():
        if not isinstance(value, list):
            continue
        case_ids = [_text(item) for item in value if _text(item)]
        if case_ids:
            out.append(f"{_text(key)}={','.join(case_ids)}")
    return out


def _full_gate_warning_diagnosis_items(report: dict[str, Any]) -> list[str]:
    full_gate = report.get("full_gate") if isinstance(report.get("full_gate"), dict) else {}
    warning_diagnoses = (
        full_gate.get("warning_diagnoses") if isinstance(full_gate.get("warning_diagnoses"), dict) else {}
    )
    out: list[str] = []
    for key, value in warning_diagnoses.items():
        if not isinstance(value, list):
            continue
        case_ids = [_text(item) for item in value if _text(item)]
        if case_ids:
            out.append(f"{_text(key)}={','.join(case_ids)}")
    return out


def _full_gate_warning_detail_items(report: dict[str, Any]) -> list[str]:
    full_gate = report.get("full_gate") if isinstance(report.get("full_gate"), dict) else {}
    warning_details = (
        full_gate.get("warning_diagnosis_details")
        if isinstance(full_gate.get("warning_diagnosis_details"), dict)
        else {}
    )
    out: list[str] = []
    for key, cases in warning_details.items():
        if not isinstance(cases, dict):
            continue
        case_items: list[str] = []
        for case_id, values in cases.items():
            if not isinstance(values, list):
                continue
            details = [_text(item) for item in values if _text(item)]
            if details and _text(case_id):
                case_items.append(f"{_text(case_id)}[{' | '.join(details)}]")
        if case_items:
            out.append(f"{_text(key)}={','.join(case_items)}")
    return out


def _metric(summary: dict[str, Any], key: str) -> str:
    value = summary.get(key)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return _text(value)
    return ""


def _knowledge_plugin_ref_summary(summary: dict[str, Any], *, raw_labels: bool = False) -> str:
    metrics = [
        ("checked", "plugin_refs_checked"),
        ("invalid", "plugin_refs_invalid"),
        ("missing_policy", "plugin_refs_missing_retrieval_policy"),
    ]
    parts: list[str] = []
    for label, key in metrics:
        value = _metric(summary, key)
        if value:
            parts.append(f"{key if raw_labels else label}={value}")
    return "; ".join(parts)


def _stage_status(report: dict[str, Any], stage: str) -> str:
    section = report.get(stage)
    if not isinstance(section, dict):
        return "unknown"
    return _text(section.get("status")) or ("passed" if section.get("passed") is True else "failed")


def _kg_compare_summary_text(kg_compare: dict[str, Any]) -> str:
    if not isinstance(kg_compare, dict) or not kg_compare:
        return ""
    summary = kg_compare.get("summary") if isinstance(kg_compare.get("summary"), dict) else {}
    candidate_gate = kg_compare.get("candidate_gate") if isinstance(kg_compare.get("candidate_gate"), dict) else {}
    parts = [
        f"candidate_gate={_metric(summary, 'candidate_gate_passed')}",
        f"compared_metrics={_metric(summary, 'compared_metrics')}",
    ]
    checks = candidate_gate.get("checks") if isinstance(candidate_gate.get("checks"), list) else []
    for check in checks:
        if not isinstance(check, dict) or _text(check.get("metric")) != "kg_noise_rate":
            continue
        parts.append(f"kg_noise_rate={_metric(check, 'actual')}")
        break
    return "; ".join(part for part in parts if not part.endswith("="))


def _retrieval_audit_summary_text(report: dict[str, Any]) -> str:
    audit = report.get("retrieval_audit") if isinstance(report.get("retrieval_audit"), dict) else {}
    if not audit:
        return ""
    plugin_refs = audit.get("plugin_refs") if isinstance(audit.get("plugin_refs"), list) else []
    hashes = audit.get("plugin_package_hashes") if isinstance(audit.get("plugin_package_hashes"), list) else []
    gates = audit.get("gates") if isinstance(audit.get("gates"), list) else []
    categories = audit.get("failure_categories") if isinstance(audit.get("failure_categories"), dict) else {}
    parts = [
        f"status={_text(audit.get('status')) or 'unknown'}",
        f"plugin_refs={len([item for item in plugin_refs if _text(item)])}",
        f"package_hashes={len([item for item in hashes if _text(item)])}",
        f"gates={len([item for item in gates if isinstance(item, dict)])}",
    ]
    failures = [_text(key) for key in categories if _text(key)]
    if failures:
        parts.append(f"failures={','.join(failures)}")
    kg_recommendation = _text(audit.get("kg_recommendation"))
    if kg_recommendation:
        parts.append(f"kg={kg_recommendation}")
    return "; ".join(parts)


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_text(cell).replace("\n", " ") for cell in row) + " |" for row in rows)
    return lines


def _report_dict(report: dict[str, Any], key: str) -> dict[str, Any]:
    value = report.get(key)
    return value if isinstance(value, dict) else {}


def format_markdown_evidence(
    report: dict[str, Any],
    *,
    console_ui_base_url: str = "",
    app_id: str = "",
) -> str:
    """Return a PII-safe Markdown evidence summary from readiness aggregate metrics."""
    summary = _report_dict(report, "summary")
    artifacts = _report_dict(report, "artifacts")
    artifact_times = _report_dict(report, "artifact_generated_at")
    knowledge_map = _report_dict(report, "knowledge_map")
    mimirq_direct = _report_dict(report, "mimirq_direct")
    kg_compare = _report_dict(report, "kg_compare")
    external_probe = _report_dict(report, "external_probe")
    full_gate = _report_dict(report, "full_gate")
    full_gate_stages = _report_dict(full_gate, "stages")
    full_eval = _report_dict(full_gate_stages, "eval")
    full_trace = _report_dict(full_gate_stages, "trace")

    knowledge_summary = _report_dict(knowledge_map, "summary")
    direct_summary = _report_dict(mimirq_direct, "summary")
    external_summary = _report_dict(external_probe, "summary")
    boundary = _report_dict(external_probe, "boundary")
    eval_summary = _report_dict(full_eval, "summary")
    trace_summary = _report_dict(full_trace, "summary")

    passed = summary.get("passed") is True
    lines = [
        "# Changzhou Dify/MimirQ Readiness Evidence",
        "",
        f"**Status:** {'PASSED' if passed else 'FAILED'}",
    ]
    generated_at = _text(report.get("generated_at"))
    if generated_at:
        lines.append(f"**Generated at:** {generated_at}")
    if _text(console_ui_base_url):
        lines.append(f"**Dify console UI:** {_join_url(console_ui_base_url, 'apps')}")
        if _text(app_id):
            lines.append(f"**Dify workflow UI:** {_join_url(console_ui_base_url, 'app', app_id, 'workflow')}")
    next_action = _text(summary.get("next_action"))
    if next_action:
        lines.append(f"**Next action:** {next_action}")
    lines.extend(
        [
            "",
            "## Stage Summary",
            "",
            *_markdown_table(
                ["Stage", "Status", "Evidence"],
                [
                    [
                        "knowledge_map",
                        _stage_status(report, "knowledge_map"),
                        f"routes={_metric(knowledge_summary, 'route_count')}; "
                        f"district_ids={_metric(knowledge_summary, 'district_knowledge_ids_checked')}; "
                        f"{_knowledge_plugin_ref_summary(knowledge_summary, raw_labels=True)}",
                    ],
                    [
                        "mimirq_direct",
                        _stage_status(report, "mimirq_direct"),
                        f"cases={_metric(direct_summary, 'cases')}; hit_at_1={_metric(direct_summary, 'hit_at_1')}; "
                        f"answer_grounding_rate={_metric(direct_summary, 'answer_grounding_rate')}; "
                        f"effective_context_rate={_metric(direct_summary, 'retrieval_effective_context_rate')}; "
                        f"noise_rate={_metric(direct_summary, 'retrieval_noise_rate')}",
                    ],
                    [
                        "kg_compare",
                        _stage_status(report, "kg_compare"),
                        _kg_compare_summary_text(kg_compare),
                    ],
                    [
                        "console_auth",
                        _stage_status(report, "console_auth"),
                        f"ttl_seconds={_metric(report.get('console_auth', {}), 'ttl_seconds')}",
                    ],
                    [
                        "external_probe",
                        _stage_status(report, "external_probe"),
                        f"verdict={_text(boundary.get('verdict'))}; "
                        f"dify_hit_nonempty={_metric(external_summary, 'dify_hit_nonempty')}; "
                        f"probe_errors={_metric(external_summary, 'probe_errors')}",
                    ],
                    [
                        "full_gate",
                        _stage_status(report, "full_gate"),
                        f"generated_answer_policy_clean_rate="
                        f"{_metric(eval_summary, 'generated_answer_policy_clean_rate')}; "
                        f"route_mismatch_cases={_metric(trace_summary, 'route_mismatch_cases')}; "
                        f"empty_retrieval_cases={_metric(trace_summary, 'empty_retrieval_cases')}",
                    ],
                ],
            ),
            "",
            "## Full Gate Metrics",
            "",
            *_markdown_table(
                ["Metric", "Value"],
                [
                    ["hit_at_1", _metric(eval_summary, "hit_at_1")],
                    ["hit_at_3", _metric(eval_summary, "hit_at_3")],
                    ["answer_grounding_rate", _metric(eval_summary, "answer_grounding_rate")],
                    ["answer_key_point_recall", _metric(eval_summary, "answer_key_point_recall")],
                    ["retrieval_effective_context_rate", _metric(eval_summary, "retrieval_effective_context_rate")],
                    ["retrieval_noise_rate", _metric(eval_summary, "retrieval_noise_rate")],
                    ["generated_answer_grounding_rate", _metric(eval_summary, "generated_answer_grounding_rate")],
                    ["generated_answer_key_point_recall", _metric(eval_summary, "generated_answer_key_point_recall")],
                    ["generated_answer_policy_clean_rate", _metric(eval_summary, "generated_answer_policy_clean_rate")],
                    ["generated_answer_fallback_rate", _metric(eval_summary, "generated_answer_fallback_rate")],
                    ["trace_errors", _metric(trace_summary, "trace_errors")],
                    ["route_mismatch_cases", _metric(trace_summary, "route_mismatch_cases")],
                    ["empty_retrieval_cases", _metric(trace_summary, "empty_retrieval_cases")],
                ],
            ),
        ]
    )
    if artifacts:
        lines.extend(["", "## Artifacts", ""])
        for key, value in artifacts.items():
            if _text(value):
                timestamp = _text(artifact_times.get(key))
                suffix = f" ({timestamp})" if timestamp else ""
                lines.append(f"- `{key}`: `{value}`{suffix}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "This evidence summary is PII-safe: it includes aggregate metrics and artifact paths only, "
            "not raw queries, generated answers, tokens, passwords, or API keys.",
        ]
    )
    return "\n".join(lines) + "\n"


def format_status(
    report: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_minutes: int | None = 30,
    console_ui_base_url: str = "",
    app_id: str = "",
) -> str:
    summary = _report_dict(report, "summary")
    artifacts = _report_dict(report, "artifacts")
    artifact_times = _report_dict(report, "artifact_generated_at")
    passed = summary.get("passed") is True
    lines = _status_header_lines(
        report,
        passed=passed,
        now=now,
        max_age_minutes=max_age_minutes,
        console_ui_base_url=console_ui_base_url,
        app_id=app_id,
    )
    if not passed:
        lines.extend(_status_failure_lines(summary))
    passed_stages = _stages_with_status(report, "passed")
    if passed_stages:
        lines.append(f"Passed stages: {', '.join(passed_stages)}")
    lines.extend(_status_context_lines(report))
    lines.extend(_status_warning_lines(report))
    skipped = _text_list(summary.get("skipped_stages"))
    if skipped:
        lines.append(f"Skipped stages: {', '.join(skipped)}")
    lines.extend(_artifact_lines("Artifact times", artifact_times))
    lines.extend(_artifact_lines("Artifacts", artifacts))
    return "\n".join(lines)


def _status_header_lines(
    report: dict[str, Any],
    *,
    passed: bool,
    now: datetime | None,
    max_age_minutes: int | None,
    console_ui_base_url: str,
    app_id: str,
) -> list[str]:
    lines = [f"Changzhou Dify readiness: {'PASSED' if passed else 'FAILED'}"]
    generated_at = _text(report.get("generated_at"))
    if generated_at:
        lines.append(f"Generated at: {generated_at}")
    lines.extend(_console_ui_lines(console_ui_base_url, app_id))
    lines.extend(_freshness_lines(generated_at, now, max_age_minutes))
    return lines


def _console_ui_lines(console_ui_base_url: str, app_id: str) -> list[str]:
    if not _text(console_ui_base_url):
        return []
    lines = [f"Dify console UI: {_join_url(console_ui_base_url, 'apps')}"]
    if _text(app_id):
        lines.append(f"Dify workflow UI: {_join_url(console_ui_base_url, 'app', app_id, 'workflow')}")
    return lines


def _freshness_lines(
    generated_at: str,
    now: datetime | None,
    max_age_minutes: int | None,
) -> list[str]:
    if not max_age_minutes or max_age_minutes <= 0:
        return []
    if not generated_at:
        return ["Freshness: unknown (missing generated_at)"]
    return [
        _freshness_line(
            generated_at,
            now=now or datetime.now(timezone.utc),
            max_age_minutes=max_age_minutes,
        )
    ]


def _status_failure_lines(summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    root_stage = _text(summary.get("root_cause_stage")) or ",".join(_text_list(summary.get("failed_stages")))
    root_reason = _text(summary.get("root_cause_reason"))
    if root_stage or root_reason:
        lines.append(f"Root cause: {root_stage}{f' ({root_reason})' if root_reason else ''}")
    next_action = _text(summary.get("next_action"))
    if next_action:
        lines.append(f"Next action: {next_action}")
    return lines


def _status_context_lines(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    external_probe = _report_dict(report, "external_probe")
    boundary = _report_dict(external_probe, "boundary")
    boundary_verdict = _text(boundary.get("verdict"))
    if boundary_verdict:
        lines.append(f"Boundary: {boundary_verdict}")
    knowledge_map = _report_dict(report, "knowledge_map")
    knowledge_summary = _report_dict(knowledge_map, "summary")
    knowledge_plugins = _knowledge_plugin_ref_summary(knowledge_summary)
    if knowledge_plugins:
        lines.append(f"Knowledge map plugins: {knowledge_plugins}")
    retrieval_audit_text = _retrieval_audit_summary_text(report)
    if retrieval_audit_text:
        lines.append(f"Retrieval audit: {retrieval_audit_text}")
    kg_compare = _report_dict(report, "kg_compare")
    kg_compare_text = _kg_compare_summary_text(kg_compare)
    if kg_compare_text:
        lines.append(f"KG compare: status={_stage_status(report, 'kg_compare')}; {kg_compare_text}")
    direct_base_line = _direct_base_line(report, external_probe)
    if direct_base_line:
        lines.append(direct_base_line)
    retrieval_quality = _retrieval_quality_line(report)
    if retrieval_quality:
        lines.append(f"Retrieval quality: {retrieval_quality}")
    return lines


def _direct_base_line(report: dict[str, Any], external_probe: dict[str, Any]) -> str:
    mimirq_direct = _report_dict(report, "mimirq_direct")
    mimirq_source = _report_dict(mimirq_direct, "source")
    direct_base_url = _text(mimirq_source.get("base_url"))
    if not direct_base_url:
        return ""
    direct_base_host = _text(mimirq_source.get("base_host"))
    external_endpoint_host = _text(external_probe.get("endpoint_host"))
    if external_endpoint_host and direct_base_host and direct_base_host != external_endpoint_host:
        return f"MimirQ direct base: {direct_base_url} (differs from external endpoint host {external_endpoint_host})"
    if external_endpoint_host and direct_base_host == external_endpoint_host:
        return f"MimirQ direct base: {direct_base_url} (matches external endpoint host)"
    return f"MimirQ direct base: {direct_base_url}"


def _retrieval_quality_line(report: dict[str, Any]) -> str:
    mimirq_direct = _report_dict(report, "mimirq_direct")
    direct_summary = _report_dict(mimirq_direct, "summary")
    full_gate = _report_dict(report, "full_gate")
    full_stages = _report_dict(full_gate, "stages")
    full_eval = _report_dict(full_stages, "eval")
    eval_summary = _report_dict(full_eval, "summary")
    retrieval_quality_parts = [
        f"direct.hit_at_1={_metric(direct_summary, 'hit_at_1')}",
        f"direct.effective_context_rate={_metric(direct_summary, 'retrieval_effective_context_rate')}",
        f"direct.noise_rate={_metric(direct_summary, 'retrieval_noise_rate')}",
        f"full.effective_context_rate={_metric(eval_summary, 'retrieval_effective_context_rate')}",
        f"full.noise_rate={_metric(eval_summary, 'retrieval_noise_rate')}",
    ]
    return "; ".join(part for part in retrieval_quality_parts if not part.endswith("="))


def _status_warning_lines(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for label, items in (
        ("Warnings", _full_gate_warning_items(report)),
        ("Warning cases", _full_gate_warning_case_items(report)),
        ("Warning diagnosis", _full_gate_warning_diagnosis_items(report)),
        ("Warning detail", _full_gate_warning_detail_items(report)),
    ):
        if items:
            lines.append(f"{label}: {'; '.join(items)}")
    return lines


def _artifact_lines(label: str, values: dict[str, Any]) -> list[str]:
    if not values:
        return []
    items = [f"{key}={value}" for key, value in values.items() if _text(value)]
    return [f"{label}: {'; '.join(items)}"] if items else []


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print compact Changzhou Dify readiness status.")
    parser.add_argument("--summary", required=True, help="Readiness summary JSON path.")
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=30,
        help="Warn when the summary generated_at is older than this many minutes. Use 0 to disable.",
    )
    parser.add_argument(
        "--console-ui-base-url",
        default="",
        help="Optional Dify console UI base URL, including any frontend base path such as /brainai.",
    )
    parser.add_argument("--app-id", default="", help="Optional Dify app id used to print the workflow UI URL.")
    parser.add_argument(
        "--markdown-out", default="", help="Optional path to write a PII-safe Markdown evidence summary."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = _load_json(str(args.summary))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Changzhou Dify readiness: UNKNOWN\nRoot cause: summary_read_error ({exc})", file=sys.stderr)
        return 2
    text = format_status(
        report,
        max_age_minutes=args.max_age_minutes,
        console_ui_base_url=str(args.console_ui_base_url),
        app_id=str(args.app_id),
    )
    print(text)
    if _text(args.markdown_out):
        markdown_path = Path(str(args.markdown_out))
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            format_markdown_evidence(
                report,
                console_ui_base_url=str(args.console_ui_base_url),
                app_id=str(args.app_id),
            ),
            encoding="utf-8",
        )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return 0 if summary.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
