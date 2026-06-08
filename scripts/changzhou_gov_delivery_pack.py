#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "mimirq.changzhou_gov.delivery_pack.v1"
DEFAULT_PLUGIN_REPORT = "/tmp/changzhou_gov_plugin_chunk_report.json"
DEFAULT_PLUGIN_CHUNK_EVIDENCE = "/tmp/changzhou_gov_plugin_chunk_evidence.json"
DEFAULT_PLUGIN_CHUNK_EVIDENCE_MARKDOWN = "/tmp/changzhou_gov_plugin_chunk_evidence.md"
DEFAULT_PLUGIN_TEST_REPORT = "/tmp/changzhou_gov_plugin_test_report.json"
DEFAULT_PLUGIN_TEST_EVIDENCE = "/tmp/changzhou_gov_plugin_test_evidence.json"
DEFAULT_READINESS_SUMMARY = "/tmp/changzhou_gov_dify_readiness_summary.json"
DEFAULT_READINESS_EVIDENCE = "/tmp/changzhou_gov_dify_readiness_evidence.md"
DEFAULT_READINESS_AUDIT = "/tmp/changzhou_gov_dify_readiness_persist_audit.json"
DEFAULT_JSON_OUT = "/tmp/changzhou_gov_delivery_pack.json"
DEFAULT_MARKDOWN_OUT = "/tmp/changzhou_gov_delivery_pack.md"
REQUIRED_PLUGIN_TEST_STAGES = ("governance", "chunk", "kg")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_json(path: str | Path) -> dict[str, Any]:
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
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _freshness(generated_at: str, *, now: datetime | None, max_age_minutes: int) -> dict[str, Any]:
    if int(max_age_minutes or 0) <= 0:
        return {
            "status": "disabled",
            "fresh": True,
            "age_minutes": 0,
            "max_age_minutes": int(max_age_minutes or 0),
        }
    parsed = _parse_timestamp(generated_at)
    if parsed is None:
        return {
            "status": "unknown",
            "fresh": False,
            "age_minutes": None,
            "max_age_minutes": int(max_age_minutes),
        }
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    age_seconds = max(0, int((checked_at - parsed).total_seconds()))
    age_minutes = age_seconds // 60
    fresh = age_seconds <= int(max_age_minutes) * 60
    return {
        "status": "fresh" if fresh else "STALE",
        "fresh": fresh,
        "age_minutes": age_minutes,
        "max_age_minutes": int(max_age_minutes),
    }


def _metric(summary: dict[str, Any], key: str) -> Any:
    value = summary.get(key)
    if isinstance(value, bool | int | float | str):
        return value
    return ""


def _nested_dict(value: Any, *keys: str) -> dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _artifact(path: str | Path, *, label: str) -> dict[str, Any]:
    target = Path(path)
    return {
        "label": label,
        "path": str(target),
        "exists": target.exists(),
        "bytes": target.stat().st_size if target.exists() else 0,
    }


def _load_optional_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    return _load_json(target)


def _count_line(values: dict[str, Any]) -> str:
    parts = []
    for key in sorted(values):
        value = values.get(key)
        if isinstance(value, int | float):
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def _plugin_sections(plugin_report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sections = plugin_report.get("sections") if isinstance(plugin_report.get("sections"), list) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        out.append(
            {
                "knowledge_section": _text(section.get("knowledge_section")),
                "governed_records": int(section.get("governed_records") or 0),
                "chunks": int(section.get("chunks") or 0),
                "kg_events": int(section.get("kg_events") or 0),
                "chunk_kinds": dict(section.get("chunk_kinds") if isinstance(section.get("chunk_kinds"), dict) else {}),
                "metadata_fields": [str(item) for item in section.get("metadata_fields", []) if _text(item)]
                if isinstance(section.get("metadata_fields"), list)
                else [],
                "kg_entity_types": [str(item) for item in section.get("kg_entity_types", []) if _text(item)]
                if isinstance(section.get("kg_entity_types"), list)
                else [],
            }
        )
    return out


def _readiness_metrics(readiness: dict[str, Any]) -> dict[str, Any]:
    direct = _nested_dict(readiness, "mimirq_direct", "summary")
    external = _nested_dict(readiness, "external_probe", "summary")
    boundary = _nested_dict(readiness, "external_probe", "boundary")
    eval_summary = _nested_dict(readiness, "full_gate", "stages", "eval", "summary")
    trace_summary = _nested_dict(readiness, "full_gate", "stages", "trace", "summary")
    return {
        "boundary": _text(boundary.get("verdict")),
        "cases": _metric(direct, "cases"),
        "hit_at_1": _metric(direct, "hit_at_1"),
        "hit_at_3": _metric(direct, "hit_at_3"),
        "dify_hit_nonempty": _metric(external, "dify_hit_nonempty"),
        "probe_errors": _metric(external, "probe_errors"),
        "generated_answer_grounding_rate": _metric(eval_summary, "generated_answer_grounding_rate"),
        "generated_answer_key_point_recall": _metric(eval_summary, "generated_answer_key_point_recall"),
        "generated_answer_policy_clean_rate": _metric(eval_summary, "generated_answer_policy_clean_rate"),
        "route_mismatch_cases": _metric(trace_summary, "route_mismatch_cases"),
        "empty_retrieval_cases": _metric(trace_summary, "empty_retrieval_cases"),
        "trace_errors": _metric(trace_summary, "trace_errors"),
    }


def _plugin_test_summary(plugin_test_report: dict[str, Any]) -> dict[str, Any]:
    stages = plugin_test_report.get("stages") if isinstance(plugin_test_report.get("stages"), dict) else {}
    stage_status: dict[str, bool] = {}
    failed_stages: list[str] = []
    for name, value in sorted(stages.items()):
        stage_passed = isinstance(value, dict) and value.get("passed") is True
        stage_status[str(name)] = stage_passed
        if not stage_passed:
            failed_stages.append(str(name))
    missing_stages = [stage for stage in REQUIRED_PLUGIN_TEST_STAGES if stage not in stage_status]
    golden_draft = _nested_dict(plugin_test_report, "golden_draft")
    return {
        "passed": plugin_test_report.get("passed") is True and not failed_stages and not missing_stages,
        "stage_count": len(stage_status),
        "stages": stage_status,
        "failed_stages": failed_stages,
        "missing_stages": missing_stages,
        "golden_draft": {
            "passed": golden_draft.get("passed") is True,
            "items_total": int(golden_draft.get("items_total") or 0),
        },
    }


def _readiness_audit_summary(readiness_audit: dict[str, Any], *, artifact_exists: bool, required: bool) -> dict[str, Any]:
    report_audit = (
        readiness_audit.get("report_retrieval_audit")
        if isinstance(readiness_audit.get("report_retrieval_audit"), dict)
        else readiness_audit
    )
    gates = report_audit.get("gates") if isinstance(report_audit.get("gates"), list) else []
    failure_categories = (
        report_audit.get("failure_categories") if isinstance(report_audit.get("failure_categories"), dict) else {}
    )
    return {
        "required": bool(required),
        "artifact_exists": bool(artifact_exists),
        "report_verified": readiness_audit.get("report_verified") is True,
        "status": _text(report_audit.get("status")),
        "plugin_refs": [str(item) for item in report_audit.get("plugin_refs", []) if _text(item)]
        if isinstance(report_audit.get("plugin_refs"), list)
        else [],
        "plugin_package_hashes": [str(item) for item in report_audit.get("plugin_package_hashes", []) if _text(item)]
        if isinstance(report_audit.get("plugin_package_hashes"), list)
        else [],
        "gate_names": [_text(gate.get("name")) for gate in gates if isinstance(gate, dict) and _text(gate.get("name"))],
        "failure_categories": {str(key): int(value or 0) for key, value in failure_categories.items()},
    }


def build_delivery_pack(
    *,
    plugin_report_path: str | Path = DEFAULT_PLUGIN_REPORT,
    plugin_chunk_evidence_path: str | Path = DEFAULT_PLUGIN_CHUNK_EVIDENCE,
    plugin_chunk_evidence_markdown_path: str | Path = DEFAULT_PLUGIN_CHUNK_EVIDENCE_MARKDOWN,
    plugin_test_report_path: str | Path = DEFAULT_PLUGIN_TEST_REPORT,
    plugin_test_evidence_path: str | Path = DEFAULT_PLUGIN_TEST_EVIDENCE,
    readiness_summary_path: str | Path = DEFAULT_READINESS_SUMMARY,
    readiness_evidence_path: str | Path = DEFAULT_READINESS_EVIDENCE,
    readiness_audit_path: str | Path = DEFAULT_READINESS_AUDIT,
    require_readiness_audit_persisted: bool = False,
    max_readiness_age_minutes: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    plugin_report = _load_json(plugin_report_path)
    plugin_chunk_evidence = _load_json(plugin_chunk_evidence_path)
    plugin_test_report = _load_json(plugin_test_report_path)
    plugin_test_evidence = _load_json(plugin_test_evidence_path)
    readiness = _load_json(readiness_summary_path)
    readiness_audit_artifact_exists = Path(readiness_audit_path).exists()
    readiness_audit_raw = _load_optional_json(readiness_audit_path)
    plugin_summary = _nested_dict(plugin_report, "summary")
    plugin_test = _plugin_test_summary(plugin_test_report)
    plugin_golden = _nested_dict(plugin_test, "golden_draft")
    readiness_summary = _nested_dict(readiness, "summary")
    readiness_metrics = _readiness_metrics(readiness)
    plugin_sections = _plugin_sections(plugin_report)
    plugin_passed = plugin_report.get("passed") is True
    plugin_chunk_evidence_passed = plugin_chunk_evidence.get("passed") is True
    plugin_test_passed = plugin_test.get("passed") is True
    plugin_test_evidence_passed = plugin_test_evidence.get("passed") is True
    plugin_golden_passed = plugin_golden.get("passed") is True
    readiness_passed = readiness_summary.get("passed") is True
    readiness_audit = _readiness_audit_summary(
        readiness_audit_raw,
        artifact_exists=readiness_audit_artifact_exists,
        required=bool(require_readiness_audit_persisted),
    )
    readiness_audit_ok = (
        readiness_audit.get("report_verified") is True if bool(require_readiness_audit_persisted) else True
    )
    freshness = _freshness(
        _text(readiness.get("generated_at")),
        now=now,
        max_age_minutes=int(max_readiness_age_minutes),
    )
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": bool(
            plugin_passed
            and plugin_chunk_evidence_passed
            and plugin_test_passed
            and plugin_test_evidence_passed
            and plugin_golden_passed
            and readiness_passed
            and freshness.get("fresh") is True
            and readiness_audit_ok
        ),
        "summary": {
            "plugin_passed": plugin_passed,
            "plugin_chunk_evidence_passed": plugin_chunk_evidence_passed,
            "plugin_test_passed": plugin_test_passed,
            "plugin_test_evidence_passed": plugin_test_evidence_passed,
            "plugin_golden_draft_passed": plugin_golden_passed,
            "plugin_golden_draft_items": int(plugin_golden.get("items_total") or 0),
            "readiness_passed": readiness_passed,
            "readiness_fresh": freshness.get("fresh") is True,
            "plugin_sections": int(plugin_summary.get("sections") or len(plugin_sections)),
            "plugin_input_documents": int(plugin_summary.get("input_documents") or 0),
            "plugin_governed_records": int(plugin_summary.get("governed_records") or 0),
            "plugin_chunks": int(plugin_summary.get("chunks") or 0),
            "plugin_kg_events": int(plugin_summary.get("kg_events") or 0),
            "readiness_stage_count": int(readiness_summary.get("stage_count") or 0),
            "readiness_failed_stages": list(readiness_summary.get("failed_stages") or []),
            "readiness_boundary": readiness_metrics["boundary"],
            "readiness_audit_report_verified": readiness_audit.get("report_verified") is True,
        },
        "artifacts": {
            "plugin_chunk_evidence_json": _artifact(plugin_chunk_evidence_path, label="plugin chunk evidence JSON"),
            "plugin_chunk_evidence_markdown": _artifact(
                plugin_chunk_evidence_markdown_path,
                label="plugin chunk evidence Markdown",
            ),
            "plugin_test_evidence_json": _artifact(plugin_test_evidence_path, label="plugin test evidence JSON"),
            "dify_readiness_summary_json": _artifact(readiness_summary_path, label="Dify readiness summary JSON"),
            "dify_readiness_evidence_markdown": _artifact(
                readiness_evidence_path,
                label="Dify readiness evidence Markdown",
            ),
            "dify_readiness_audit_json": _artifact(
                readiness_audit_path,
                label="Dify readiness retrieval audit persistence JSON",
            ),
        },
        "plugin": {
            "id": _text(_nested_dict(plugin_report, "plugin").get("id")),
            "version": _text(_nested_dict(plugin_report, "plugin").get("version")),
            "package_hash": _text(_nested_dict(plugin_report, "plugin").get("package_hash")),
            "generated_at": _text(plugin_report.get("generated_at")),
            "sections": plugin_sections,
            "test": plugin_test,
        },
        "readiness": {
            "generated_at": _text(readiness.get("generated_at")),
            "failed_stages": list(readiness_summary.get("failed_stages") or []),
            "skipped_stages": list(readiness_summary.get("skipped_stages") or []),
            "root_cause_stage": _text(readiness_summary.get("root_cause_stage")),
            "root_cause_reason": _text(readiness_summary.get("root_cause_reason")),
            "next_action": _text(readiness_summary.get("next_action")),
            "metrics": readiness_metrics,
            "freshness": freshness,
            "audit": readiness_audit,
        },
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_text(cell).replace("\n", " ").replace("|", "\\|") for cell in row) + " |" for row in rows)
    return lines


def _join_inline(values: list[str], *, limit: int = 10) -> str:
    return ", ".join(f"`{value}`" for value in values[:limit])


def format_markdown_pack(pack: dict[str, Any]) -> str:
    summary = pack.get("summary") if isinstance(pack.get("summary"), dict) else {}
    artifacts = pack.get("artifacts") if isinstance(pack.get("artifacts"), dict) else {}
    plugin = pack.get("plugin") if isinstance(pack.get("plugin"), dict) else {}
    plugin_test = plugin.get("test") if isinstance(plugin.get("test"), dict) else {}
    plugin_golden = plugin_test.get("golden_draft") if isinstance(plugin_test.get("golden_draft"), dict) else {}
    readiness = pack.get("readiness") if isinstance(pack.get("readiness"), dict) else {}
    metrics = readiness.get("metrics") if isinstance(readiness.get("metrics"), dict) else {}
    freshness = readiness.get("freshness") if isinstance(readiness.get("freshness"), dict) else {}
    readiness_audit = readiness.get("audit") if isinstance(readiness.get("audit"), dict) else {}
    lines = [
        "# Changzhou Gov Delivery Pack",
        "",
        f"**Status:** {'PASSED' if pack.get('passed') is True else 'FAILED'}",
        f"**Generated at:** {_text(pack.get('generated_at'))}",
        f"**Plugin:** {_text(plugin.get('id'))}@{_text(plugin.get('version'))}",
        "",
        "## Summary",
        "",
        *_markdown_table(
            [
                "plugin_passed",
                "plugin_chunk_evidence_passed",
                "plugin_test_passed",
                "plugin_test_evidence_passed",
                "golden_items",
                "readiness_passed",
                "readiness_fresh",
                "audit_report_verified",
                "sections",
                "records",
                "chunks",
                "kg_events",
                "boundary",
            ],
            [
                [
                    _text(summary.get("plugin_passed")),
                    _text(summary.get("plugin_chunk_evidence_passed")),
                    _text(summary.get("plugin_test_passed")),
                    _text(summary.get("plugin_test_evidence_passed")),
                    _text(summary.get("plugin_golden_draft_items")),
                    _text(summary.get("readiness_passed")),
                    _text(summary.get("readiness_fresh")),
                    _text(summary.get("readiness_audit_report_verified")),
                    _text(summary.get("plugin_sections")),
                    _text(summary.get("plugin_governed_records")),
                    _text(summary.get("plugin_chunks")),
                    _text(summary.get("plugin_kg_events")),
                    _text(summary.get("readiness_boundary")),
                ]
            ],
        ),
        "",
        "## Plugin Contract Test",
        "",
        *_markdown_table(
            ["Metric", "Value"],
            [
                ["passed", _text(plugin_test.get("passed"))],
                ["stage_count", _text(plugin_test.get("stage_count"))],
                ["failed_stages", ", ".join(plugin_test.get("failed_stages") or [])],
                ["missing_stages", ", ".join(plugin_test.get("missing_stages") or [])],
                ["golden_draft_passed", _text(plugin_golden.get("passed"))],
                ["golden_draft_items", _text(plugin_golden.get("items_total"))],
            ],
        ),
        "",
        "## Plugin Section Matrix",
        "",
        *_markdown_table(
            ["Section", "Records", "Chunks", "KG Events", "chunk_kinds", "metadata_fields", "kg_entity_types"],
            [
                [
                    _text(section.get("knowledge_section")),
                    _text(section.get("governed_records")),
                    _text(section.get("chunks")),
                    _text(section.get("kg_events")),
                    _count_line(section.get("chunk_kinds") if isinstance(section.get("chunk_kinds"), dict) else {}),
                    _join_inline(section.get("metadata_fields") if isinstance(section.get("metadata_fields"), list) else []),
                    _join_inline(section.get("kg_entity_types") if isinstance(section.get("kg_entity_types"), list) else []),
                ]
                for section in (plugin.get("sections") if isinstance(plugin.get("sections"), list) else [])
                if isinstance(section, dict)
            ],
        ),
        "",
        "## Dify/MimirQ Readiness Metrics",
        "",
        *_markdown_table(["Metric", "Value"], [[key, _text(value)] for key, value in metrics.items()]),
        "",
        "## Retrieval Audit Persistence",
        "",
        *_markdown_table(
            ["Metric", "Value"],
            [
                ["required", _text(readiness_audit.get("required"))],
                ["artifact_exists", _text(readiness_audit.get("artifact_exists"))],
                ["audit_report_verified", _text(readiness_audit.get("report_verified"))],
                ["status", _text(readiness_audit.get("status"))],
                ["plugin_refs", ", ".join(readiness_audit.get("plugin_refs") or [])],
                ["plugin_package_hashes", ", ".join(readiness_audit.get("plugin_package_hashes") or [])],
                ["gates", ", ".join(readiness_audit.get("gate_names") or [])],
                [
                    "failure_categories",
                    _count_line(
                        readiness_audit.get("failure_categories")
                        if isinstance(readiness_audit.get("failure_categories"), dict)
                        else {}
                    ),
                ],
            ],
        ),
        "",
        "## Readiness Freshness",
        "",
        *_markdown_table(
            ["status", "fresh", "age_minutes", "max_age_minutes"],
            [
                [
                    _text(freshness.get("status")),
                    _text(freshness.get("fresh")),
                    _text(freshness.get("age_minutes")),
                    _text(freshness.get("max_age_minutes")),
                ]
            ],
        ),
        "",
        "## Artifacts",
        "",
        *_markdown_table(
            ["Artifact", "Exists", "Bytes", "Path"],
            [
                [
                    _text(value.get("label")),
                    _text(value.get("exists")),
                    _text(value.get("bytes")),
                    _text(value.get("path")),
                ]
                for value in artifacts.values()
                if isinstance(value, dict)
            ],
        ),
        "",
        "## Reproduce",
        "",
        "```bash",
        "make changzhou-gov-plugin-chunk-report",
        "make changzhou-gov-plugin-test-report",
        "make changzhou-dify-readiness-evidence",
        "make changzhou-gov-delivery-pack",
        "```",
        "",
        "## Safety",
        "",
        "This delivery pack intentionally includes aggregate metrics, section matrices, and artifact paths only. "
        "It does not copy plugin example previews, Golden draft sample questions, raw Dify queries, generated answers, "
        "tokens, passwords, or API keys.",
    ]
    return "\n".join(lines) + "\n"


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Changzhou Gov delivery evidence pack index.")
    parser.add_argument("--plugin-report", default=DEFAULT_PLUGIN_REPORT)
    parser.add_argument("--plugin-chunk-evidence", default=DEFAULT_PLUGIN_CHUNK_EVIDENCE)
    parser.add_argument("--plugin-chunk-evidence-markdown", default=DEFAULT_PLUGIN_CHUNK_EVIDENCE_MARKDOWN)
    parser.add_argument("--plugin-test-report", default=DEFAULT_PLUGIN_TEST_REPORT)
    parser.add_argument("--plugin-test-evidence", default=DEFAULT_PLUGIN_TEST_EVIDENCE)
    parser.add_argument("--readiness-summary", default=DEFAULT_READINESS_SUMMARY)
    parser.add_argument("--readiness-evidence", default=DEFAULT_READINESS_EVIDENCE)
    parser.add_argument("--readiness-audit", default=DEFAULT_READINESS_AUDIT)
    parser.add_argument("--require-readiness-audit-persisted", action="store_true")
    parser.add_argument("--max-readiness-age-minutes", type=int, default=30)
    parser.add_argument("--json-out", default=DEFAULT_JSON_OUT, help="Write JSON pack to this path, or '-' for stdout.")
    parser.add_argument("--markdown-out", default=DEFAULT_MARKDOWN_OUT, help="Write Markdown pack to this path. Empty disables it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        pack = build_delivery_pack(
            plugin_report_path=args.plugin_report,
            plugin_chunk_evidence_path=args.plugin_chunk_evidence,
            plugin_chunk_evidence_markdown_path=args.plugin_chunk_evidence_markdown,
            plugin_test_report_path=args.plugin_test_report,
            plugin_test_evidence_path=args.plugin_test_evidence,
            readiness_summary_path=args.readiness_summary,
            readiness_evidence_path=args.readiness_evidence,
            readiness_audit_path=args.readiness_audit,
            require_readiness_audit_persisted=bool(args.require_readiness_audit_persisted),
            max_readiness_age_minutes=int(args.max_readiness_age_minutes),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-gov-delivery-pack] ERROR: {exc}", file=sys.stderr)
        return 2
    json_text = json.dumps(pack, ensure_ascii=False, indent=2) + "\n"
    if _text(args.json_out) == "-":
        print(json_text, end="")
    else:
        _write_text(args.json_out, json_text)
    if _text(args.markdown_out):
        _write_text(args.markdown_out, format_markdown_pack(pack))
    return 0 if pack.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
