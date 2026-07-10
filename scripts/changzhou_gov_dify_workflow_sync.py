#!/usr/bin/env python3
"""Safely stage or apply a sanitized Dify draft workflow.

The default mode is dry-run: fetch the current draft, write a backup, build the
POST payload, and report lint deltas. Remote writes require explicit --apply.
"""


import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.changzhou_gov_dify_trace_report import (  # noqa: E402
    DEFAULT_CONSOLE_BASE_URL,
    DEFAULT_STORAGE_STATE,
    load_console_token,
)
from scripts.changzhou_gov_dify_workflow_lint import lint_workflow  # noqa: E402

RequestJsonFn = Callable[..., dict[str, Any]]

_REQUEST_ATTEMPTS = 3
_SCHEMA = "mimirq.changzhou_gov_service_knowledge.dify_workflow_sync.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: str | os.PathLike[str], payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_workflow_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow JSON must be an object")
    return payload


def _request_json(
    *,
    console_base_url: str,
    console_token: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    url = f"{console_base_url.rstrip('/')}/{path.lstrip('/')}"
    data = None
    headers = {
        "Authorization": f"Bearer {console_token}",
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, method=method.upper(), headers=headers)
    last_error: URLError | None = None
    for _attempt in range(_REQUEST_ATTEMPTS):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
        except URLError as exc:
            last_error = exc
    raise RuntimeError(f"request failed: {last_error}") from last_error


def _workflow_value(
    target_workflow: dict[str, Any],
    current_workflow: dict[str, Any],
    key: str,
    expected_type: type,
    fallback: Any,
) -> Any:
    target_value = target_workflow.get(key)
    if isinstance(target_value, expected_type):
        return target_value
    current_value = current_workflow.get(key)
    if isinstance(current_value, expected_type):
        return current_value
    return fallback


def build_sync_payload(current_workflow: dict[str, Any], target_workflow: dict[str, Any]) -> dict[str, Any]:
    """Build the Dify draft sync payload from target content and current draft hash."""
    graph = target_workflow.get("graph")
    if not isinstance(graph, dict):
        raise ValueError("target workflow graph must be an object")

    payload: dict[str, Any] = {
        "graph": graph,
        "features": _workflow_value(target_workflow, current_workflow, "features", dict, {}),
        "environment_variables": _workflow_value(
            target_workflow,
            current_workflow,
            "environment_variables",
            list,
            [],
        ),
        "conversation_variables": _workflow_value(
            target_workflow,
            current_workflow,
            "conversation_variables",
            list,
            [],
        ),
    }
    current_hash = _text(current_workflow.get("hash"))
    if current_hash:
        payload["hash"] = current_hash
    return payload


def _summary_count(report: dict[str, Any], key: str) -> int:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return int(summary.get(key) or 0)


def sync_workflow_draft(
    *,
    app_id: str,
    target_workflow: dict[str, Any],
    console_base_url: str,
    console_token: str,
    request_json: RequestJsonFn = _request_json,
    timeout: float = 30.0,
    backup_out: str | os.PathLike[str] | None = None,
    payload_out: str | os.PathLike[str] | None = None,
    apply: bool = False,
    allow_prompt_leaks: bool = False,
    expected_current_hash: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    app_id = _text(app_id)
    if not app_id:
        raise ValueError("app_id is required")
    if not _text(console_token):
        raise ValueError("console_token is required")

    draft_path = f"/apps/{app_id}/workflows/draft"
    current_workflow = request_json(
        console_base_url=console_base_url,
        console_token=console_token,
        path=draft_path,
        method="GET",
        payload=None,
        timeout=timeout,
    )
    if not isinstance(current_workflow, dict):
        raise ValueError("current draft workflow response must be an object")

    expected_hash = _text(expected_current_hash)
    current_hash = _text(current_workflow.get("hash"))
    if expected_hash and current_hash != expected_hash:
        raise ValueError(f"current draft hash mismatch: expected {expected_hash}, got {current_hash or '<empty>'}")

    if backup_out is not None and _text(backup_out):
        _write_json(backup_out, current_workflow)

    current_lint = lint_workflow(current_workflow)
    target_lint = lint_workflow(target_workflow)
    payload = build_sync_payload(current_workflow, target_workflow)

    if payload_out is not None and _text(payload_out):
        _write_json(payload_out, payload)

    current_prompt_leaks = _summary_count(current_lint, "prompt_template_leak_warnings")
    target_prompt_leaks = _summary_count(target_lint, "prompt_template_leak_warnings")
    current_http_json_template_warnings = _summary_count(current_lint, "http_json_template_warnings")
    target_http_json_template_warnings = _summary_count(target_lint, "http_json_template_warnings")
    report: dict[str, Any] = {
        "schema": _SCHEMA,
        "generated_at": generated_at or _utc_now_text(),
        "app_id": app_id,
        "draft_path": draft_path,
        "dry_run": not apply,
        "applied": False,
        "backup_out": str(backup_out or ""),
        "payload_out": str(payload_out or ""),
        "summary": {
            "current_prompt_template_leak_warnings": current_prompt_leaks,
            "target_prompt_template_leak_warnings": target_prompt_leaks,
            "current_http_json_template_warnings": current_http_json_template_warnings,
            "target_http_json_template_warnings": target_http_json_template_warnings,
            "posted": False,
            "verified_after_post": False,
        },
        "current_lint": current_lint,
        "target_lint": target_lint,
    }

    if apply and target_prompt_leaks > 0 and not allow_prompt_leaks:
        raise ValueError("target workflow has prompt-template leaks; refusing to apply")
    if apply and target_http_json_template_warnings > 0:
        raise ValueError("target workflow has HTTP JSON template bodies; refusing to apply")
    if not apply:
        return report

    post_response = request_json(
        console_base_url=console_base_url,
        console_token=console_token,
        path=draft_path,
        method="POST",
        payload=payload,
        timeout=timeout,
    )
    verified_workflow = request_json(
        console_base_url=console_base_url,
        console_token=console_token,
        path=draft_path,
        method="GET",
        payload=None,
        timeout=timeout,
    )
    post_verify_lint = lint_workflow(verified_workflow)

    report["applied"] = True
    report["post_response"] = post_response
    report["post_verify_lint"] = post_verify_lint
    report["summary"]["posted"] = True
    report["summary"]["verified_after_post"] = True
    report["summary"]["post_verify_prompt_template_leak_warnings"] = _summary_count(
        post_verify_lint,
        "prompt_template_leak_warnings",
    )
    report["summary"]["post_verify_http_json_template_warnings"] = _summary_count(
        post_verify_lint,
        "http_json_template_warnings",
    )
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run or apply a sanitized Dify draft workflow.")
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--workflow-json", required=True)
    parser.add_argument("--console-base-url", default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or DEFAULT_CONSOLE_BASE_URL)
    parser.add_argument("--console-token", default=os.getenv("DIFY_CONSOLE_TOKEN") or "")
    parser.add_argument("--storage-state", default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--payload-out", default="")
    parser.add_argument("--expected-current-hash", default="")
    parser.add_argument("--allow-prompt-leaks", action="store_true")
    parser.add_argument("--apply", action="store_true", help="POST the staged payload to the Dify draft workflow.")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        console_token = load_console_token(str(args.console_token), str(args.storage_state))
        if not console_token:
            print("DIFY_CONSOLE_TOKEN, --console-token, or --storage-state with console_token is required", file=sys.stderr)
            return 2
        target_workflow = _load_workflow_json(str(args.workflow_json))
        report = sync_workflow_draft(
            app_id=str(args.app_id),
            target_workflow=target_workflow,
            console_base_url=str(args.console_base_url),
            console_token=console_token,
            timeout=float(args.timeout),
            backup_out=str(args.backup_out),
            payload_out=str(args.payload_out),
            apply=bool(args.apply),
            allow_prompt_leaks=bool(args.allow_prompt_leaks),
            expected_current_hash=str(args.expected_current_hash),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-dify-workflow-sync] ERR: {exc}", file=sys.stderr)
        return 1

    _write_json(str(args.out), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    issue_count = int(summary.get("target_prompt_template_leak_warnings") or 0) + int(
        summary.get("post_verify_prompt_template_leak_warnings") or 0
    ) + int(
        summary.get("target_http_json_template_warnings") or 0
    ) + int(
        summary.get("post_verify_http_json_template_warnings") or 0
    )
    return 0 if issue_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
