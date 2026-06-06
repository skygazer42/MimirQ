#!/usr/bin/env python3
"""Compare Dify external dataset hit-testing with direct MimirQ retrieval.

This is a read-only boundary diagnostic. It does not modify a Dify workflow or
MimirQ data; it only proves which side of the Dify external-knowledge boundary
is returning empty results.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

DEFAULT_CONSOLE_BASE_URL = "https://dify.example.com:5001/console/api"
DEFAULT_STORAGE_STATE = "/tmp/dify_console_storage_state.json"
DEFAULT_EXTERNAL_API_LIMIT = 50

RequestJsonFn = Callable[..., dict[str, Any]]
RequestMimirqDirectFn = Callable[..., dict[str, Any]]


def _text(value: Any) -> str:
    return str(value or "").strip()


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


def _request_json(
    *,
    console_base_url: str,
    console_token: str,
    path: str,
    timeout: float,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {
        "Authorization": f"Bearer {console_token}",
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{console_base_url.rstrip('/')}/{path.lstrip('/')}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


def _request_mimirq_direct(
    *,
    endpoint: str,
    api_key: str,
    knowledge_id: str,
    query: str,
    top_k: int,
    timeout: float,
) -> dict[str, Any]:
    payload = {
        "knowledge_id": knowledge_id,
        "query": query,
        "retrieval_setting": {
            "top_k": top_k,
            "score_threshold": 0,
        },
    }
    request = Request(
        f"{endpoint.rstrip('/')}/retrieval",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


def load_cases(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("cases file must be an object with cases[] or a cases[] list")
    return [item for item in cases if isinstance(item, dict)]


def _external_apis_path(limit: int = DEFAULT_EXTERNAL_API_LIMIT) -> str:
    return f"/datasets/external-knowledge-api?page=1&limit={limit}"


def _select_external_api(payload: dict[str, Any], external_api_id: str) -> dict[str, Any]:
    apis = payload.get("data")
    if not isinstance(apis, list):
        raise ValueError("Dify external knowledge API response does not contain data[]")
    if external_api_id:
        for item in apis:
            if isinstance(item, dict) and item.get("id") == external_api_id:
                return item
        raise ValueError(f"Dify external knowledge API not found: {external_api_id}")
    mimirq_apis = [
        item
        for item in apis
        if isinstance(item, dict) and "mimirq" in _text(item.get("name")).lower()
    ]
    if len(mimirq_apis) == 1:
        return mimirq_apis[0]
    raise ValueError("Pass --external-api-id when Dify has zero or multiple MimirQ external APIs")


def build_knowledge_dataset_map(
    *,
    dataset_bindings: list[dict[str, Any]],
    console_base_url: str,
    console_token: str,
    request_json: RequestJsonFn = _request_json,
    timeout: float = 30.0,
) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for binding in dataset_bindings:
        dataset_id = _text(binding.get("id"))
        if not dataset_id:
            continue
        detail = request_json(
            console_base_url=console_base_url,
            console_token=console_token,
            path=f"/datasets/{dataset_id}",
            timeout=timeout,
        )
        info = detail.get("external_knowledge_info") if isinstance(detail, dict) else {}
        if not isinstance(info, dict):
            info = {}
        knowledge_id = _text(info.get("external_knowledge_id"))
        if not knowledge_id:
            continue
        mapping[knowledge_id] = {
            "dataset_id": dataset_id,
            "dataset_name": _text(detail.get("name") or binding.get("name")),
            "external_retrieval_model": detail.get("external_retrieval_model") if isinstance(detail, dict) else None,
        }
    return mapping


def _records_count(payload: dict[str, Any]) -> int:
    records = payload.get("records")
    if isinstance(records, list):
        return len(records)
    data = payload.get("data")
    if isinstance(data, list):
        return len(data)
    return 0


def _first_record_title(payload: dict[str, Any]) -> str:
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return ""
    first = records[0]
    if not isinstance(first, dict):
        return ""
    metadata = first.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return _text(metadata.get("document_name") or first.get("title") or metadata.get("title"))


def validate_dify_external_records_shape(payload: dict[str, Any]) -> list[str]:
    records = payload.get("records")
    if not isinstance(records, list):
        return ["records must be a list"]
    errors: list[str] = []
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"records[{idx}] must be an object")
            continue
        if not _text(record.get("content")):
            errors.append(f"records[{idx}].content must be a non-empty string")
        score = record.get("score")
        if not isinstance(score, int | float) or score < 0 or score > 1:
            errors.append(f"records[{idx}].score must be between 0 and 1")
        if not _text(record.get("title")):
            errors.append(f"records[{idx}].title must be a non-empty string")
        metadata = record.get("metadata")
        if "metadata" in record and not isinstance(metadata, dict):
            errors.append(f"records[{idx}].metadata must be an object when present")
    return errors


def _diagnosis(*, dify_count: int, direct_count: int, missing_dataset: bool, error: str) -> str:
    if error:
        return "probe_error"
    if missing_dataset:
        return "missing_dify_dataset_binding"
    if dify_count == 0 and direct_count > 0:
        return "dify_runtime_empty_but_mimirq_direct_ok"
    if dify_count > 0:
        return "dify_hit_testing_ok"
    return "both_empty"


def _external_hit_testing_payload(*, query: str, top_k: int, mapped: dict[str, Any]) -> dict[str, Any]:
    model = mapped.get("external_retrieval_model") if isinstance(mapped.get("external_retrieval_model"), dict) else {}
    external_retrieval_model = {
        "top_k": int(model.get("top_k") or top_k),
        "score_threshold": float(model.get("score_threshold") or 0),
        "score_threshold_enabled": bool(model.get("score_threshold_enabled") or False),
    }
    return {
        "query": query,
        "external_retrieval_model": external_retrieval_model,
    }


def collect_probe_report(
    *,
    cases: list[dict[str, Any]],
    external_api_id: str,
    console_base_url: str,
    console_token: str,
    request_json: RequestJsonFn = _request_json,
    request_mimirq_direct: RequestMimirqDirectFn = _request_mimirq_direct,
    timeout: float = 30.0,
    top_k: int = 5,
) -> dict[str, Any]:
    external_payload = request_json(
        console_base_url=console_base_url,
        console_token=console_token,
        path=_external_apis_path(),
        timeout=timeout,
    )
    external_api = _select_external_api(external_payload, external_api_id)
    settings = external_api.get("settings") if isinstance(external_api.get("settings"), dict) else {}
    endpoint = _text(settings.get("endpoint"))
    api_key = _text(settings.get("api_key"))
    bindings = external_api.get("dataset_bindings") if isinstance(external_api.get("dataset_bindings"), list) else []
    dataset_map = build_knowledge_dataset_map(
        dataset_bindings=[item for item in bindings if isinstance(item, dict)],
        console_base_url=console_base_url,
        console_token=console_token,
        request_json=request_json,
        timeout=timeout,
    )

    rows: list[dict[str, Any]] = []
    for case in cases:
        case_id = _text(case.get("id") or case.get("case_id"))
        knowledge_id = _text(case.get("knowledge_id"))
        query = _text(case.get("query"))
        mapped = dataset_map.get(knowledge_id, {})
        dataset_id = _text(mapped.get("dataset_id"))
        dify_payload: dict[str, Any] = {}
        direct_payload: dict[str, Any] = {}
        error = ""
        try:
            if dataset_id:
                dify_payload = request_json(
                    console_base_url=console_base_url,
                    console_token=console_token,
                    path=f"/datasets/{dataset_id}/external-hit-testing",
                    timeout=timeout,
                    method="POST",
                    payload=_external_hit_testing_payload(query=query, top_k=top_k, mapped=mapped),
                )
            if endpoint and api_key and knowledge_id and query:
                direct_payload = request_mimirq_direct(
                    endpoint=endpoint,
                    api_key=api_key,
                    knowledge_id=knowledge_id,
                    query=query,
                    top_k=top_k,
                    timeout=timeout,
                )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        dify_count = _records_count(dify_payload)
        direct_count = _records_count(direct_payload)
        direct_schema_errors = validate_dify_external_records_shape(direct_payload) if direct_payload else []
        rows.append(
            {
                "id": case_id,
                "query": query,
                "knowledge_id": knowledge_id,
                "dify_dataset_id": dataset_id,
                "dify_dataset_name": _text(mapped.get("dataset_name")),
                "dify_hit_records": dify_count,
                "mimirq_direct_records": direct_count,
                "mimirq_direct_schema_valid": not direct_schema_errors,
                "mimirq_direct_schema_errors": direct_schema_errors,
                "mimirq_direct_first_title": _first_record_title(direct_payload),
                "diagnosis": _diagnosis(
                    dify_count=dify_count,
                    direct_count=direct_count,
                    missing_dataset=not bool(dataset_id),
                    error=error,
                ),
                **({"error": error} if error else {}),
            }
        )

    return {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_external_knowledge_probe.v1",
        "source": {
            "provider": "dify",
            "console_base_url": console_base_url.rstrip("/"),
            "external_api_id": _text(external_api.get("id")),
            "external_api_name": _text(external_api.get("name")),
            "endpoint": endpoint,
            "dataset_bindings": len(bindings),
        },
        "summary": {
            "cases": len(rows),
            "dify_hit_nonempty": sum(1 for row in rows if int(row.get("dify_hit_records") or 0) > 0),
            "dify_hit_empty": sum(1 for row in rows if int(row.get("dify_hit_records") or 0) == 0),
            "mimirq_direct_nonempty": sum(1 for row in rows if int(row.get("mimirq_direct_records") or 0) > 0),
            "mimirq_direct_schema_valid": sum(1 for row in rows if bool(row.get("mimirq_direct_schema_valid"))),
            "dify_runtime_empty_but_mimirq_direct_ok": sum(
                1 for row in rows if row.get("diagnosis") == "dify_runtime_empty_but_mimirq_direct_ok"
            ),
            "probe_errors": sum(1 for row in rows if row.get("error")),
        },
        "cases": rows,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Dify external knowledge hit-testing against direct MimirQ retrieval.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--external-api-id", default=os.getenv("DIFY_EXTERNAL_KNOWLEDGE_API_ID") or "")
    parser.add_argument("--console-base-url", default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or DEFAULT_CONSOLE_BASE_URL)
    parser.add_argument("--console-token", default=os.getenv("DIFY_CONSOLE_TOKEN") or "")
    parser.add_argument("--storage-state", default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    console_token = load_console_token(str(args.console_token), str(args.storage_state))
    if not console_token:
        print("DIFY_CONSOLE_TOKEN, --console-token, or --storage-state with console_token is required", file=sys.stderr)
        return 2
    try:
        report = collect_probe_report(
            cases=load_cases(str(args.cases)),
            external_api_id=str(args.external_api_id),
            console_base_url=str(args.console_base_url),
            console_token=console_token,
            timeout=float(args.timeout),
            top_k=int(args.top_k),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-dify-external-probe] ERR: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if int((report.get("summary") or {}).get("probe_errors") or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
