#!/usr/bin/env python3

import argparse
import json
import sys
import warnings
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# This CLI runs local plugin checks, not the production API service.
warnings.filterwarnings(
    "ignore",
    message=r"SECRET_KEY is not configured\..*",
    category=UserWarning,
)

from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test  # noqa: E402
from app.rag.pipeline_plugins.registry import (  # noqa: E402
    PipelinePluginDescriptor,
    PipelinePluginRegistryError,
    describe_plugin_dir,
)
from app.rag.pipeline_plugins.reports import build_pipeline_plugin_chunk_report  # noqa: E402

PLUGIN_RELEASE_GATE_SCHEMA = "mimirq.plugin_release_gate.v1"
_STAGE_ORDER = ("governance", "chunk", "kg")


def _check(
    name: str,
    *,
    passed: bool,
    required: bool = True,
    status: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "passed": bool(passed),
        "required": bool(required),
        "status": status or ("passed" if passed else "failed"),
    }
    if details:
        out["details"] = details
    return out


def _gate_summary(checks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    failed_required = [
        str(check.get("name"))
        for check in checks
        if check.get("required") is not False and check.get("passed") is not True and check.get("name")
    ]
    failed_optional = [
        str(check.get("name"))
        for check in checks
        if check.get("required") is False and check.get("passed") is not True and check.get("name")
    ]
    return {
        "checks_total": len(checks),
        "required_checks": sum(1 for check in checks if check.get("required") is not False),
        "failed_required_checks": failed_required,
        "failed_optional_checks": failed_optional,
    }


def _descriptor_payload(descriptor: PipelinePluginDescriptor) -> dict[str, Any]:
    return {
        "id": descriptor.id,
        "version": descriptor.version,
        "name": descriptor.name,
        "published": descriptor.published,
        "executable": descriptor.executable,
        "test_status": descriptor.test_status,
        "package_hash": descriptor.package_hash,
        "refs": dict(descriptor.refs),
        "contract_summary": dict(descriptor.contract_summary or {}),
    }


def _summarize_stage_report(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"passed": False, "input_count": 0, "output_count": 0, "output_chars": 0, "validation_ok": False}
    validation = (
        raw.get("kg_validation") if isinstance(raw.get("kg_validation"), dict) else raw.get("metadata_validation")
    )
    return {
        "passed": raw.get("passed") is True,
        "input_count": int(raw.get("input_count") or 0),
        "output_count": int(raw.get("output_count") or 0),
        "output_chars": int(raw.get("output_chars") or 0),
        "validation_ok": validation.get("ok") is True if isinstance(validation, dict) else False,
    }


def _summarize_local_test(report: dict[str, Any]) -> dict[str, Any]:
    raw_stages = report.get("stages") if isinstance(report.get("stages"), dict) else {}
    stages = {
        stage: _summarize_stage_report(raw_stages.get(stage))
        for stage in _STAGE_ORDER
        if isinstance(raw_stages, dict) and stage in raw_stages
    }
    golden = report.get("golden_draft") if isinstance(report.get("golden_draft"), dict) else {}
    return {
        "passed": report.get("passed") is True,
        "stages": stages,
        "golden_draft": {
            "passed": golden.get("passed") is True if golden else False,
            "items_total": int(golden.get("items_total") or 0) if isinstance(golden, dict) else 0,
        },
    }


def _summarize_chunk_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": dict(report.get("summary") or {}),
        "readiness": dict(report.get("readiness") or {}),
    }


def _chunk_readiness_details(chunk_summary: dict[str, Any]) -> dict[str, Any]:
    readiness = chunk_summary.get("readiness") if isinstance(chunk_summary.get("readiness"), dict) else {}
    checks = readiness.get("checks") if isinstance(readiness.get("checks"), list) else []
    failed = [
        str(check.get("name"))
        for check in checks
        if isinstance(check, dict)
        and check.get("required") is not False
        and check.get("passed") is not True
        and check.get("name")
    ]
    errors: list[dict[str, str]] = []
    for check in checks:
        if not isinstance(check, dict) or check.get("passed") is True:
            continue
        name = str(check.get("name") or "").strip()
        for item in check.get("errors") or []:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or "").strip()
            if name and reason:
                errors.append({"check": name, "reason": reason[:300]})
    details = {
        "readiness_status": str(readiness.get("status") or "unavailable"),
        "failed_readiness_checks": failed,
    }
    if errors:
        details["failed_readiness_errors"] = errors[:5]
    return details


def _safe_failure_reason(prefix: str, exc: BaseException) -> str:
    return f"{prefix}: {type(exc).__name__}"


def _declared_stages(descriptor: PipelinePluginDescriptor, stages: Sequence[str] | None) -> list[str]:
    if stages:
        return [stage for stage in _STAGE_ORDER if stage in set(stages)]
    return [stage for stage in _STAGE_ORDER if stage in descriptor.entries]


def build_plugin_release_gate_report(
    plugin_dir: str | Path,
    *,
    sample_path: str | Path,
    stages: Sequence[str] | None = None,
    require_retrieval_policy: bool = False,
) -> dict[str, Any]:
    plugin_path = Path(plugin_dir)
    checks: list[dict[str, Any]] = []
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        descriptor = describe_plugin_dir(plugin_path, require_test_report=False)
    except PipelinePluginRegistryError as exc:
        checks.append(
            _check(
                "manifest_contracts_valid",
                passed=False,
                details={"reason": str(exc)[:300]},
            )
        )
        return {
            "schema": PLUGIN_RELEASE_GATE_SCHEMA,
            "generated_at": generated_at,
            "passed": False,
            "summary": _gate_summary(checks),
            "plugin": {"dir": str(plugin_path)},
            "checks": checks,
        }

    checks.append(_check("manifest_contracts_valid", passed=True))
    checks.append(
        _check(
            "metadata_schema_declared",
            passed=bool(descriptor.metadata_schema),
            details={"fields": len((descriptor.metadata_schema or {}).get("fields") or [])},
        )
    )
    checks.append(
        _check(
            "retrieval_policy_declared",
            passed=bool(descriptor.retrieval_policy),
            required=require_retrieval_policy,
            status="passed" if descriptor.retrieval_policy else "not_declared",
        )
    )
    checks.append(_check("governance_stage_declared", passed="governance" in descriptor.entries))
    checks.append(_check("chunk_stage_declared", passed="chunk" in descriptor.entries))

    selected_stages = _declared_stages(descriptor, stages)
    local_report: dict[str, Any] = {}
    descriptor_after = descriptor
    if selected_stages:
        local_report = run_pipeline_plugin_test(
            plugin_path,
            input_path=sample_path,
            stages=selected_stages,
            write_report=True,
        )
        checks.append(_check("local_stage_test_passed", passed=local_report.get("passed") is True))
        descriptor_after = describe_plugin_dir(plugin_path, require_test_report=True)
        checks.append(
            _check(
                "local_test_report_current",
                passed=descriptor_after.executable and descriptor_after.test_status == "passed",
                details={"test_status": descriptor_after.test_status},
            )
        )
    else:
        checks.append(_check("local_stage_test_passed", passed=False, details={"reason": "no declared stages"}))
        checks.append(_check("local_test_report_current", passed=False, details={"test_status": "missing"}))

    chunk_summary: dict[str, Any] = {"summary": {}, "readiness": {"status": "failed", "checks": []}}
    if "governance" in descriptor.entries and "chunk" in descriptor.entries:
        try:
            chunk_report = build_pipeline_plugin_chunk_report(
                plugin_path,
                input_path=sample_path,
                max_examples_per_section=0,
                preview_chars=40,
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _check(
                    "chunk_report_ready",
                    passed=False,
                    details={
                        "reason": _safe_failure_reason("chunk report generation failed", exc),
                        **_chunk_readiness_details(chunk_summary),
                    },
                )
            )
        else:
            chunk_summary = _summarize_chunk_report(chunk_report)
            chunk_ready = (chunk_summary.get("readiness") or {}).get("status") == "passed"
            checks.append(
                _check(
                    "chunk_report_ready",
                    passed=chunk_ready,
                    details=_chunk_readiness_details(chunk_summary),
                )
            )
    else:
        checks.append(
            _check(
                "chunk_report_ready",
                passed=False,
                details={"reason": "governance and chunk stages are required for a release chunk report"},
            )
        )

    golden_declared = (descriptor.golden_rules or {}).get("schema") == "mimirq.golden_rules.v1"
    golden_summary = (_summarize_local_test(local_report).get("golden_draft") if local_report else {}) or {}
    golden_passed = golden_summary.get("passed") is True and int(golden_summary.get("items_total") or 0) > 0
    checks.append(
        _check(
            "golden_draft_available",
            passed=golden_passed if golden_declared else True,
            required=golden_declared,
            status="passed" if golden_passed else ("not_declared" if not golden_declared else "failed"),
            details={"items_total": int(golden_summary.get("items_total") or 0)} if golden_declared else None,
        )
    )

    required_checks = [check for check in checks if bool(check.get("required"))]
    return {
        "schema": PLUGIN_RELEASE_GATE_SCHEMA,
        "generated_at": generated_at,
        "passed": all(bool(check.get("passed")) for check in required_checks),
        "summary": _gate_summary(checks),
        "plugin": _descriptor_payload(descriptor_after),
        "checks": checks,
        "local_test": _summarize_local_test(local_report),
        "chunk_report": chunk_summary,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a generic MimirQ pipeline plugin release gate.")
    parser.add_argument(
        "--plugin-dir", required=True, help="Plugin package directory containing mimirq-plugin.json/yaml."
    )
    parser.add_argument(
        "--sample", required=True, dest="sample_path", help="JSON sample input: array or {documents:[...]}."
    )
    parser.add_argument(
        "--stage",
        action="append",
        choices=list(_STAGE_ORDER),
        dest="stages",
        help="Stage to test. Repeat for multiple stages. Defaults to every entry in the manifest.",
    )
    parser.add_argument(
        "--require-retrieval-policy",
        action="store_true",
        help="Fail the gate if the plugin does not declare mimirq.retrieval_policy.v1.",
    )
    parser.add_argument("--out", default="-", help="Output JSON path, or '-' for stdout (default: %(default)s).")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_plugin_release_gate_report(
        args.plugin_dir,
        sample_path=args.sample_path,
        stages=args.stages,
        require_retrieval_policy=args.require_retrieval_policy,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if str(args.out or "-") == "-":
        print(text)
    else:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
