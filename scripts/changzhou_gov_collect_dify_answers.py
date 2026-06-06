#!/usr/bin/env python3
"""Collect generated answers from a fixed Dify app for Changzhou golden cases.

This script does not modify a Dify workflow. It only calls the published App API
with fixed golden questions and writes an answers JSON that can be scored by
`scripts/changzhou_gov_golden_eval.py --answers`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.changzhou_gov_golden_eval import DEFAULT_CASES, load_cases  # noqa: E402

DEFAULT_DIFY_BASE_URL = "http://127.0.0.1/v1"
DEFAULT_API_KEY_FILE = "/tmp/dify_app_api_keys_post.json"
_REQUEST_ATTEMPTS = 3
RequestJsonFn = Callable[..., dict[str, Any]]
ProgressFn = Callable[[dict[str, Any]], None]
_TRACEABLE_DIFY_INPUT_KEYS = {"areaName"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _case_dify_inputs(case: dict[str, Any]) -> dict[str, Any]:
    raw = case.get("dify_inputs")
    if raw is None:
        raw = case.get("app_inputs")
    if not isinstance(raw, dict):
        return {}
    return {_text(key): value for key, value in raw.items() if _text(key)}


def _traceable_case_dify_inputs(case: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in _case_dify_inputs(case).items() if key in _TRACEABLE_DIFY_INPUT_KEYS}


def build_dify_payload(
    case: dict[str, Any],
    *,
    mode: str,
    user: str,
    response_mode: str,
    workflow_query_key: str,
) -> dict[str, Any]:
    query = _text(case.get("query"))
    inputs = _case_dify_inputs(case)
    if str(mode).strip().lower() == "workflow":
        return {
            "inputs": {**inputs, workflow_query_key: query},
            "response_mode": response_mode,
            "user": user,
        }
    return {
        "inputs": inputs,
        "query": query,
        "response_mode": response_mode,
        "user": user,
        "auto_generate_name": False,
    }


def _endpoint_path(mode: str) -> str:
    return "/workflows/run" if str(mode).strip().lower() == "workflow" else "/chat-messages"


def _api_url(base_url: str, *, mode: str) -> str:
    return f"{str(base_url or '').rstrip('/')}{_endpoint_path(mode)}"


def extract_dify_answer(response: dict[str, Any]) -> str:
    for key in ("answer", "text", "content", "result"):
        value = _text(response.get(key))
        if value:
            return value
    data = response.get("data")
    if isinstance(data, dict):
        outputs = data.get("outputs")
        if isinstance(outputs, dict):
            for key in ("answer", "text", "content", "result", "output"):
                value = _text(outputs.get(key))
                if value:
                    return value
        value = _text(data.get("answer") or data.get("text") or data.get("result"))
        if value:
            return value
    return ""


def extract_dify_response_refs(response: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    containers = [response]
    data = response.get("data")
    if isinstance(data, dict):
        containers.append(data)
    for container in containers:
        for key in ("conversation_id", "message_id", "task_id", "workflow_run_id"):
            value = _text(container.get(key))
            if value and key not in out:
                out[key] = value
    return out


def _extract_http_error_payload(message: str) -> dict[str, Any]:
    prefix = "HTTP "
    if not message.startswith(prefix):
        return {}
    marker = ": "
    marker_index = message.find(marker)
    if marker_index < 0:
        return {}
    status_text = message[len(prefix) : marker_index].strip()
    payload_text = message[marker_index + len(marker) :].strip()
    out: dict[str, Any] = {}
    if status_text.isdigit():
        out["http_status"] = int(status_text)
    if payload_text.startswith("{"):
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            code = _text(payload.get("code"))
            detail = _text(payload.get("message"))
            if code:
                out["dify_error_code"] = code
            if detail:
                out["dify_error_message"] = detail
    return out


def _extract_missing_variable_selector(message: str) -> str:
    start_marker = "Variable #"
    start = message.find(start_marker)
    if start < 0:
        return ""
    start += len(start_marker)
    end = message.find("# not found", start)
    if end < 0:
        return ""
    return message[start:end].strip()


def diagnose_dify_error(message: str) -> dict[str, Any]:
    """Return non-secret, structured diagnostics for common Dify API errors."""
    text = _text(message)
    if not text:
        return {}
    out = _extract_http_error_payload(text)
    detail = _text(out.get("dify_error_message")) or text
    selector = _extract_missing_variable_selector(detail)
    if selector:
        variable = selector.rsplit(".", 1)[-1].strip()
        out.update(
            {
                "error_kind": "missing_start_variable",
                "missing_variable_selector": selector,
                "missing_variable": variable,
            }
        )
    return out


def _request_json(*, url: str, payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    last_error: URLError | None = None
    for _attempt in range(_REQUEST_ATTEMPTS):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
        except URLError as exc:
            last_error = exc
    raise RuntimeError(f"request failed: {last_error}") from last_error


def load_api_key(api_key: str, api_key_file: str, *, env: Mapping[str, str] | None = None) -> str:
    explicit = _text(api_key)
    if explicit:
        return explicit
    source_env = env if env is not None else os.environ
    from_env = _text(source_env.get("DIFY_APP_API_KEY"))
    if from_env:
        return from_env
    key_file = Path(_text(api_key_file))
    if not key_file.is_file():
        return ""
    payload = json.loads(key_file.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for key in ("token", "api_key", "key"):
            value = _text(payload.get(key))
            if value:
                return value
    return ""


def collect_answers(
    *,
    cases: list[dict[str, Any]],
    base_url: str,
    api_key: str,
    mode: str,
    user: str,
    response_mode: str,
    workflow_query_key: str,
    timeout: float,
    request_json: RequestJsonFn = _request_json,
    interval_sec: float = 0.0,
    progress_fn: ProgressFn | None = None,
    generated_at: str = "",
) -> dict[str, Any]:
    answers: list[dict[str, Any]] = []
    url = _api_url(base_url, mode=mode)
    total = len(cases)
    for index, case in enumerate(cases, start=1):
        case_id = _text(case.get("id"))
        query = _text(case.get("query"))
        item: dict[str, Any] = {"id": case_id, "query": query}
        traceable_inputs = _traceable_case_dify_inputs(case)
        if traceable_inputs:
            item["dify_inputs"] = traceable_inputs
        try:
            payload = build_dify_payload(
                case,
                mode=mode,
                user=user,
                response_mode=response_mode,
                workflow_query_key=workflow_query_key,
            )
            response = request_json(url=url, payload=payload, api_key=api_key, timeout=timeout)
            answer = extract_dify_answer(response)
            item.update({"answer": answer, "ok": bool(answer)})
            item.update(extract_dify_response_refs(response))
            if not answer:
                item["error"] = "empty answer"
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            item.update({"answer": "", "ok": False, "error": error})
            item.update(diagnose_dify_error(error))
        answers.append(item)
        if progress_fn is not None:
            progress_fn(
                {
                    "stage": "collect",
                    "event": "case",
                    "index": index,
                    "total": total,
                    "id": case_id,
                    "ok": bool(item.get("ok")),
                }
            )
        if interval_sec > 0:
            time.sleep(float(interval_sec))
    succeeded = sum(1 for item in answers if item.get("ok") is True)
    missing_variable_errors = sum(1 for item in answers if item.get("error_kind") == "missing_start_variable")
    summary: dict[str, Any] = {
        "cases": len(answers),
        "succeeded": succeeded,
        "failed": len(answers) - succeeded,
    }
    if missing_variable_errors:
        summary["missing_start_variable_errors"] = missing_variable_errors
    return {
        "schema": "mimirq.changzhou_gov_service_knowledge.generated_answers.v1",
        "generated_at": _text(generated_at) or _utc_now_text(),
        "source": {
            "provider": "dify",
            "mode": str(mode),
            "base_url": str(base_url).rstrip("/"),
            "endpoint_url": url,
        },
        "summary": summary,
        "answers": answers,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Dify generated answers for Changzhou golden cases.")
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--base-url", default=os.getenv("DIFY_API_BASE_URL") or DEFAULT_DIFY_BASE_URL)
    parser.add_argument("--api-key", default=os.getenv("DIFY_APP_API_KEY") or "")
    parser.add_argument("--api-key-file", default=DEFAULT_API_KEY_FILE)
    parser.add_argument("--mode", choices=["chat", "workflow"], default="chat")
    parser.add_argument("--response-mode", choices=["blocking", "streaming"], default="blocking")
    parser.add_argument("--workflow-query-key", default="query")
    parser.add_argument("--user", default="mimirq-golden-eval")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--interval-sec", type=float, default=0.0)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    api_key = load_api_key(str(args.api_key), str(args.api_key_file))
    if not api_key:
        print("DIFY_APP_API_KEY, --api-key, or --api-key-file is required", file=sys.stderr)
        return 2
    report = collect_answers(
        cases=load_cases(str(args.cases)),
        base_url=str(args.base_url),
        api_key=api_key,
        mode=str(args.mode),
        user=str(args.user),
        response_mode=str(args.response_mode),
        workflow_query_key=str(args.workflow_query_key),
        timeout=float(args.timeout),
        interval_sec=float(args.interval_sec),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if int((report.get("summary") or {}).get("failed") or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
