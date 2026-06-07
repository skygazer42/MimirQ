#!/usr/bin/env python3
"""Build a node-level Dify workflow trace report from collected golden answers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CONSOLE_BASE_URL = "https://dify.example.com:5001/console/api"
DEFAULT_STORAGE_STATE = "/tmp/dify_console_storage_state.json"
RequestJsonFn = Callable[..., dict[str, Any]]
ProgressFn = Callable[[dict[str, Any]], None]

_FALLBACK_ANSWER_MARKERS = (
    "只能答复常州市政务服务领域",
    "超出领域的问题",
    "暂时无法回答",
)
_REQUEST_ATTEMPTS = 3
_CITY_AREA_NAMES = {"常州市本级", "常州市", "常州全市", "全市"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_fallback_answer(answer: str) -> bool:
    text = _text(answer)
    return bool(text) and all(marker in text for marker in _FALLBACK_ANSWER_MARKERS)


def _is_console_auth_error(message: Any) -> bool:
    text = _text(message).lower()
    return "http 401" in text or "token has expired" in text or "unauthorized" in text


def load_console_token(
    console_token: str,
    storage_state: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    explicit = _text(console_token)
    if explicit:
        return explicit
    source_env = env if env is not None else os.environ
    from_env = _text(source_env.get("DIFY_CONSOLE_TOKEN"))
    if from_env:
        return from_env
    state_path = Path(_text(storage_state))
    if not state_path.is_file():
        return ""
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    for origin in payload.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        for item in origin.get("localStorage") or []:
            if isinstance(item, dict) and item.get("name") == "console_token":
                value = _text(item.get("value"))
                if value:
                    return value
    return ""


def _request_json(*, console_base_url: str, console_token: str, path: str, timeout: float) -> dict[str, Any]:
    url = f"{console_base_url.rstrip('/')}/{path.lstrip('/')}"
    request = Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {console_token}",
            "Accept": "application/json",
        },
    )
    last_error: Exception | None = None
    for _attempt in range(_REQUEST_ATTEMPTS):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
        except (TimeoutError, URLError) as exc:
            last_error = exc
    raise RuntimeError(f"request failed: {last_error}") from last_error


def load_answers(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    answers = payload.get("answers") if isinstance(payload, dict) else payload
    if not isinstance(answers, list):
        raise ValueError("answers report must be an object with answers[] or an answers[] list")
    return [item for item in answers if isinstance(item, dict)]


def _message_path(app_id: str, message_id: str) -> str:
    return f"/apps/{app_id}/messages/{message_id}"


def _node_executions_path(app_id: str, workflow_run_id: str) -> str:
    return f"/apps/{app_id}/workflow-runs/{workflow_run_id}/node-executions"


def _execution_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _result_count(outputs: Any) -> int | None:
    if not isinstance(outputs, dict):
        return None
    result = outputs.get("result")
    if isinstance(result, list):
        return len(result)
    return None


def _result_titles(outputs: Any) -> list[str]:
    if not isinstance(outputs, dict):
        return []
    result = outputs.get("result")
    if not isinstance(result, list):
        return []
    titles: list[str] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        title = _text(item.get("title") or item.get("document_name") or metadata.get("document_name") or metadata.get("title"))
        if title:
            titles.append(title)
    return titles


def _expected_area(answer_item: dict[str, Any]) -> str:
    inputs = answer_item.get("dify_inputs")
    if isinstance(inputs, dict):
        value = _text(inputs.get("areaName"))
        if value:
            return value
    return _text(answer_item.get("expected_area"))


def _expected_retrieval_title_contains(expected_area: str) -> str:
    area = _text(expected_area)
    if not area:
        return ""
    if area in _CITY_AREA_NAMES:
        return "常州市"
    return area


def _region_texts(regions: list[Any]) -> list[str]:
    out: list[str] = []
    for region in regions:
        if isinstance(region, dict):
            for key in ("region", "area"):
                value = _text(region.get(key))
                if value:
                    out.append(value)
        else:
            value = _text(region)
            if value:
                out.append(value)
    return out


def _region_extractor_summary(title: str, node_type: str, outputs: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "title": title,
        "node_type": node_type,
    }
    if "__is_success" in outputs:
        summary["success"] = bool(outputs.get("__is_success"))
    reason = _text(outputs.get("__reason"))
    if reason:
        summary["reason"] = reason
    for key in ("region", "area"):
        if key in outputs:
            summary[key] = _text(outputs.get(key))
    return summary


def _add_route_diagnostics(answer_item: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    expected_area = _expected_area(answer_item)
    if not expected_area:
        return {}
    expected_title = _expected_retrieval_title_contains(expected_area)
    retrievals = summary.get("retrievals") if isinstance(summary.get("retrievals"), list) else []
    node_titles = [_text(item.get("title")) for item in retrievals if isinstance(item, dict)]
    result_titles = [
        title
        for item in retrievals
        if isinstance(item, dict)
        for title in item.get("result_titles", [])
        if _text(title)
    ]
    node_route_matched = any(expected_title in title for title in node_titles if title) if expected_title else True
    evidence_route_matched = (
        any(expected_title in _text(title) for title in result_titles) if expected_title and result_titles else None
    )
    route_matched = bool(node_route_matched or evidence_route_matched is True)
    regions = summary.get("regions") if isinstance(summary.get("regions"), list) else []
    region_values = _region_texts(regions)
    region_matched = any(expected_area == value for value in region_values) if region_values else None
    out: dict[str, Any] = {
        "expected_area": expected_area,
        "expected_retrieval_title_contains": expected_title,
        "node_route_matched": node_route_matched,
        "route_matched": route_matched,
    }
    if evidence_route_matched is not None:
        out["evidence_route_matched"] = evidence_route_matched
    if node_route_matched is False and evidence_route_matched is True:
        out["route_compensated"] = True
    if region_matched is not None:
        out["region_matched"] = region_matched
    return out


def _summarize_executions(executions: list[dict[str, Any]]) -> dict[str, Any]:
    retrievals: list[dict[str, Any]] = []
    regions: list[Any] = []
    region_extractors: list[dict[str, Any]] = []
    answer_node_title = ""
    for execution in executions:
        title = _text(execution.get("title"))
        node_type = _text(execution.get("node_type"))
        outputs = execution.get("outputs")
        if node_type == "knowledge-retrieval":
            inputs = execution.get("inputs") if isinstance(execution.get("inputs"), dict) else {}
            retrievals.append(
                {
                    "title": title,
                    "query": _text(inputs.get("query")),
                    "count": _result_count(outputs),
                    "result_titles": _result_titles(outputs),
                }
            )
        if "区域提取器" in title and isinstance(outputs, dict):
            region = outputs.get("region") or outputs.get("area") or outputs
            regions.append(region)
            region_extractors.append(_region_extractor_summary(title, node_type, outputs))
        if node_type == "answer" and not answer_node_title:
            answer_node_title = title
    return {
        "answer_node_title": answer_node_title,
        "regions": regions,
        "region_extractors": region_extractors,
        "retrievals": retrievals,
    }


def _trace_answer(
    answer_item: dict[str, Any],
    *,
    app_id: str,
    console_base_url: str,
    console_token: str,
    request_json: RequestJsonFn,
    timeout: float,
) -> dict[str, Any]:
    case_id = _text(answer_item.get("id") or answer_item.get("case_id"))
    query = _text(answer_item.get("query"))
    message_id = _text(answer_item.get("message_id"))
    workflow_run_id = _text(answer_item.get("workflow_run_id"))
    if not message_id and not workflow_run_id:
        out: dict[str, Any] = {"id": case_id, "query": query, "error": "missing message_id"}
        upstream_error = _text(answer_item.get("error"))
        if upstream_error:
            out["upstream_error"] = upstream_error
        for key in (
            "error_kind",
            "http_status",
            "dify_error_code",
            "dify_error_message",
            "missing_variable_selector",
            "missing_variable",
        ):
            value = answer_item.get(key)
            if value not in (None, ""):
                out[key] = value
        return out

    message: dict[str, Any] = {}
    if not workflow_run_id:
        message = request_json(
            console_base_url=console_base_url,
            console_token=console_token,
            path=_message_path(app_id, message_id),
            timeout=timeout,
        )
        workflow_run_id = _text(message.get("workflow_run_id"))
    if not workflow_run_id:
        return {"id": case_id, "query": query, "message_id": message_id, "error": "missing workflow_run_id"}

    node_payload = request_json(
        console_base_url=console_base_url,
        console_token=console_token,
        path=_node_executions_path(app_id, workflow_run_id),
        timeout=timeout,
    )
    executions = _execution_rows(node_payload)
    summary = _summarize_executions(executions)
    answer = _text(message.get("answer") or answer_item.get("answer"))
    route_diagnostics = _add_route_diagnostics(answer_item, summary)
    return {
        "id": case_id,
        "query": query,
        "message_id": message_id,
        "workflow_run_id": workflow_run_id,
        "fallback": _is_fallback_answer(answer),
        **summary,
        **route_diagnostics,
    }


def collect_trace_report(
    *,
    answers: list[dict[str, Any]],
    app_id: str,
    console_base_url: str,
    console_token: str,
    request_json: RequestJsonFn = _request_json,
    timeout: float = 30.0,
    progress_fn: ProgressFn | None = None,
    generated_at: str = "",
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    total = len(answers)
    for index, item in enumerate(answers, start=1):
        case_id = _text(item.get("id") or item.get("case_id"))
        try:
            row = _trace_answer(
                item,
                app_id=app_id,
                console_base_url=console_base_url,
                console_token=console_token,
                request_json=request_json,
                timeout=timeout,
            )
            cases.append(row)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            row = {"id": item.get("id"), "query": item.get("query"), "error": error}
            if _is_console_auth_error(error):
                row["error_kind"] = "dify_console_auth"
            cases.append(row)
        if progress_fn is not None:
            progress_fn(
                {
                    "stage": "trace",
                    "event": "case",
                    "index": index,
                    "total": total,
                    "id": case_id,
                    "ok": not bool(cases[-1].get("error")),
                }
            )

    traced_cases = [item for item in cases if not item.get("error")]
    retrieval_cases = [item for item in traced_cases if isinstance(item.get("retrievals"), list)]
    empty_retrieval_cases = [
        item
        for item in retrieval_cases
        if item.get("retrievals") and all((entry.get("count") or 0) == 0 for entry in item.get("retrievals") or [])
    ]
    nonempty_retrieval_cases = [
        item
        for item in retrieval_cases
        if any((entry.get("count") or 0) > 0 for entry in item.get("retrievals") or [])
    ]
    summary: dict[str, Any] = {
        "cases": len(cases),
        "traced": len(traced_cases),
        "fallback_cases": sum(1 for item in traced_cases if bool(item.get("fallback"))),
        "empty_retrieval_cases": len(empty_retrieval_cases),
        "nonempty_retrieval_cases": len(nonempty_retrieval_cases),
        "trace_errors": sum(1 for item in cases if item.get("error")),
    }
    expected_area_cases = sum(1 for item in traced_cases if _text(item.get("expected_area")))
    if expected_area_cases:
        summary["expected_area_cases"] = expected_area_cases
        summary["node_route_mismatch_cases"] = sum(1 for item in traced_cases if item.get("node_route_matched") is False)
        summary["route_compensated_cases"] = sum(1 for item in traced_cases if item.get("route_compensated") is True)
        summary["route_mismatch_cases"] = sum(1 for item in traced_cases if item.get("route_matched") is False)
        summary["region_mismatch_cases"] = sum(1 for item in traced_cases if item.get("region_matched") is False)
    upstream_error_cases = sum(1 for item in cases if item.get("upstream_error"))
    if upstream_error_cases:
        summary["upstream_error_cases"] = upstream_error_cases
    missing_variable_errors = sum(1 for item in cases if item.get("error_kind") == "missing_start_variable")
    if missing_variable_errors:
        summary["missing_start_variable_errors"] = missing_variable_errors
    console_auth_errors = sum(1 for item in cases if item.get("error_kind") == "dify_console_auth")
    if console_auth_errors:
        summary["console_auth_errors"] = console_auth_errors
    return {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_trace_report.v1",
        "generated_at": _text(generated_at) or _utc_now_text(),
        "source": {
            "provider": "dify",
            "console_base_url": console_base_url.rstrip("/"),
            "app_id": app_id,
        },
        "summary": summary,
        "cases": cases,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Dify node-execution trace report for golden answers.")
    parser.add_argument("--answers", required=True)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--console-base-url", default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or DEFAULT_CONSOLE_BASE_URL)
    parser.add_argument("--console-token", default=os.getenv("DIFY_CONSOLE_TOKEN") or "")
    parser.add_argument("--storage-state", default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    console_token = load_console_token(str(args.console_token), str(args.storage_state))
    if not console_token:
        print("DIFY_CONSOLE_TOKEN, --console-token, or --storage-state with console_token is required", file=sys.stderr)
        return 2
    try:
        report = collect_trace_report(
            answers=load_answers(str(args.answers)),
            app_id=str(args.app_id),
            console_base_url=str(args.console_base_url),
            console_token=console_token,
            timeout=float(args.timeout),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-dify-trace] ERR: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if int((report.get("summary") or {}).get("trace_errors") or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
