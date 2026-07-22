#!/usr/bin/env python3
"""Run Dify/MimirQ app benchmarks against deterministic rubrics.

The benchmark is intentionally evidence-first:

- Generate 800 cases from existing native-data rubrics (human mixed + golden).
- Call each Dify App with the same question/input payload.
- Score answers and any retriever resources with deterministic evidence clauses.
- Emit machine-readable artifacts plus a compact Markdown comparison.

No App API key is written to output artifacts.
"""


import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.changzhou_gov_collect_dify_answers import (  # noqa: E402
    _request_json,
    build_dify_payload,
    diagnose_dify_error,
    extract_dify_answer,
    extract_dify_response_refs,
    load_cases,
)
from scripts.evaluate_mixed_rag_quality import (  # noqa: E402
    build_markdown_report,
    evaluate_mixed_rag_quality,
)
from scripts.rag_e2e_load_test import summarize_latencies_ms, throughput_per_sec  # noqa: E402

DEFAULT_BASE_URL = "https://dify.example.com:5001/v1"
DEFAULT_CASES = os.getenv("DIFY_3WAY_CASES", "")
DEFAULT_GOLDEN_CASES = os.getenv("DIFY_3WAY_GOLDEN_CASES", "")
DEFAULT_OUT_DIR = "artifacts/dify_3way_benchmark"
DEFAULT_TARGET_COUNT = 800
DEFAULT_MIMIRQ_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_RETRY_MULTIPLIER = 2.0
TIMEOUT_RETRY_MIN_ADD_SEC = 30.0
TIMEOUT_RETRY_MAX_SEC = 600.0

DEFAULT_APP_SPECS = [
    {
        "label": "dify_http_mimirq",
        "app_id": "00000000-0000-0000-0000-000000000002",
        "kind": "http_to_mimirq",
        "description": "Dify HTTP 节点调用 MimirQ",
    },
    {
        "label": "dify_native_kb",
        "app_id": "00000000-0000-0000-0000-000000000001",
        "kind": "native_dify_knowledge",
        "description": "原生 Dify 知识库",
    },
]

QUESTION_VARIANTS = [
    ("mixed", "{question}"),
    ("qa", "{title}这个事项，帮我直接说清楚：{dims}。"),
    ("simulated_user", "我想办理“{title}”，不想跑错窗口，{dims}帮我一起核一下。"),
    ("mixed_followup", "{title}这个事前面没太看懂，主要想确认{dims}，按现在政策怎么说？"),
    ("plain_user", "麻烦查一下{title}，{dims}。"),
    ("noisy_user", "{title}是不是能办？我这边比较急，{dims}，最好给我依据。"),
    ("operator_check", "请按政务知识库口径核对“{title}”：{dims}。"),
    ("short_user", "{title}：{dims}？"),
]


@dataclass(frozen=True)
class AppSpec:
    label: str
    app_id: str
    kind: str
    description: str
    api_key: str
    mode: str = "chat"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _case_id(case: dict[str, Any]) -> str:
    return _text(case.get("id") or case.get("case_id"))


def _case_question(case: dict[str, Any]) -> str:
    return _text(case.get("question") or case.get("query"))


def _case_title(case: dict[str, Any]) -> str:
    for key in ("source_record_title", "service_name", "title"):
        value = _text(case.get(key))
        if value:
            return value
    question = _case_question(case)
    if "「" in question and "」" in question:
        return question.split("「", 1)[1].split("」", 1)[0].strip()
    return question[:36] or _case_id(case)


def _dimension_text(case: dict[str, Any]) -> str:
    fields = case.get("dimension_fields")
    if isinstance(fields, list):
        values = [_text(item) for item in fields if _text(item)]
        if values:
            return "、".join(values)

    subquestions = case.get("subquestions")
    if isinstance(subquestions, list):
        values: list[str] = []
        for item in subquestions:
            if isinstance(item, dict):
                value = _text(item.get("id") or item.get("name"))
            else:
                value = _text(item)
            if value:
                values.append(value)
        if values:
            return "、".join(values[:4])

    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    points = expected.get("answer_key_points") if isinstance(expected.get("answer_key_points"), list) else []
    if points:
        return "、".join(_text(point).split("：", 1)[0] for point in points[:4] if _text(point))
    return "办理层级、时间、材料和咨询方式"


def _with_query(case: dict[str, Any], *, case_id: str, query: str, case_type: str, source_case_id: str) -> dict[str, Any]:
    out = dict(case)
    out["id"] = case_id
    out["query"] = query
    out["question"] = query
    out["case_type"] = case_type
    out["source_case_id"] = source_case_id
    out["benchmark_generation"] = "dify_3way_800_v1"
    return out


def build_benchmark_cases(
    *,
    mixed_cases: list[dict[str, Any]],
    golden_cases: list[dict[str, Any]],
    target_count: int,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    source_cases = [dict(item) for item in mixed_cases if _case_id(item)]
    source_cases.extend(dict(item) for item in golden_cases if _case_id(item))
    if not source_cases:
        raise ValueError("no source cases available")

    rng.shuffle(source_cases)
    cases: list[dict[str, Any]] = []
    variant_index = 0
    while len(cases) < target_count:
        source = source_cases[len(cases) % len(source_cases)]
        source_id = _case_id(source)
        title = _case_title(source)
        dims = _dimension_text(source)
        variant_name, template = QUESTION_VARIANTS[variant_index % len(QUESTION_VARIANTS)]
        if variant_name == "mixed":
            query = _case_question(source)
        else:
            query = template.format(question=_case_question(source), title=title, dims=dims)
        query = " ".join(query.split())
        case_id = f"bench-{len(cases) + 1:04d}-{variant_name}-{source_id}"
        cases.append(_with_query(source, case_id=case_id, query=query, case_type=variant_name, source_case_id=source_id))
        variant_index += 1
    return cases


def resolve_expected_case_count(
    *,
    prebuilt_cases: str,
    target_count: int,
    cases: list[dict[str, Any]],
) -> int:
    if _text(prebuilt_cases):
        return len(cases)
    return int(target_count)


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def count_by(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for case in cases:
            value = _text(case.get(key)) or "unknown"
            out[value] = out.get(value, 0) + 1
        return dict(sorted(out.items(), key=lambda item: (-item[1], item[0])))

    source_sections: dict[str, int] = {}
    for case in cases:
        section = _text(case.get("source_section"))
        if not section:
            source_file = _text(case.get("source_file"))
            section = source_file.split("/", 1)[0] if "/" in source_file else "unknown"
        source_sections[section] = source_sections.get(section, 0) + 1

    return {
        "cases": len(cases),
        "by_case_type": count_by("case_type"),
        "by_knowledge_id": count_by("knowledge_id"),
        "by_source_section": dict(sorted(source_sections.items(), key=lambda item: (-item[1], item[0]))),
        "unique_source_cases": len({_text(case.get("source_case_id")) or _case_id(case) for case in cases}),
    }


def select_cases_to_run(cases: list[dict[str, Any]], *, limit: int = 0, sample_per_type: int = 0) -> list[dict[str, Any]]:
    per_type = int(sample_per_type or 0)
    if per_type > 0:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for case in cases:
            grouped.setdefault(_text(case.get("case_type")) or "unknown", []).append(case)
        selected: list[dict[str, Any]] = []
        for case_type in sorted(grouped):
            selected.extend(grouped[case_type][:per_type])
        selected.sort(key=lambda case: _case_id(case))
        return selected

    run_limit = int(limit or 0)
    return cases[:run_limit] if run_limit > 0 else cases


def build_truth_manifest(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        clauses = case.get("evidence_clauses") if isinstance(case.get("evidence_clauses"), list) else []
        subquestions = case.get("subquestions") if isinstance(case.get("subquestions"), list) else []
        rows.append(
            {
                "case_id": _case_id(case),
                "source_case_id": _text(case.get("source_case_id")),
                "case_type": _text(case.get("case_type")),
                "knowledge_id": _text(case.get("knowledge_id")),
                "query": _case_question(case),
                "source_file": _text(case.get("source_file")),
                "source_section": _text(case.get("source_section")),
                "source_record_title": _text(case.get("source_record_title")),
                "dimension_fields": case.get("dimension_fields") if isinstance(case.get("dimension_fields"), list) else [],
                "subquestion_ids": [
                    _text(item.get("id")) if isinstance(item, dict) else _text(item)
                    for item in subquestions
                    if _text(item.get("id") if isinstance(item, dict) else item)
                ],
                "evidence_clause_ids": [
                    _text(item.get("id")) if isinstance(item, dict) else _text(item)
                    for item in clauses
                    if _text(item.get("id") if isinstance(item, dict) else item)
                ],
                "evidence_clause_terms": [
                    {
                        "id": _text(item.get("id")),
                        "required_terms": item.get("required_terms") if isinstance(item.get("required_terms"), list) else [],
                    }
                    for item in clauses
                    if isinstance(item, dict)
                ],
            }
        )
    return rows


def load_prebuilt_cases(path: str) -> list[dict[str, Any]]:
    payload = load_cases(path)
    if isinstance(payload, dict):
        cases = payload.get("cases")
        if isinstance(cases, list):
            return [dict(item) for item in cases if isinstance(item, dict)]
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    raise ValueError("prebuilt cases file must be a list or an object with cases[]")


def _endpoint_path(mode: str) -> str:
    return "/workflows/run" if mode == "workflow" else "/chat-messages"


def _endpoint_url(base_url: str, mode: str) -> str:
    return f"{base_url.rstrip('/')}{_endpoint_path(mode)}"


def _fixed_mode(mode: str) -> str:
    mode = _text(mode) or "chat"
    return mode if mode in {"chat", "workflow", "auto"} else "chat"


def _fixed_response_mode(response_mode: str) -> str:
    response_mode = _text(response_mode) or "blocking"
    return response_mode if response_mode in {"blocking", "streaming"} else "blocking"


def _iter_dify_sse_payloads(lines: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _stream_payload_to_response(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    answer_parts: list[str] = []
    response: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    outputs: dict[str, Any] = {}

    for payload in payloads:
        event = _text(payload.get("event"))
        if event == "error":
            message = _text(payload.get("message") or payload.get("code") or "Dify streaming error")
            raise RuntimeError(message)

        answer = _text(payload.get("answer"))
        if answer:
            answer_parts.append(answer)

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        data_outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
        if data_outputs:
            outputs.update(data_outputs)

        payload_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if payload_metadata:
            metadata.update(payload_metadata)

        data_metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if data_metadata:
            metadata.update(data_metadata)

        for key in ("conversation_id", "task_id", "workflow_run_id"):
            value = _text(payload.get(key) or data.get(key))
            if value and key not in response:
                response[key] = value

        message_id = _text(payload.get("message_id") or data.get("message_id"))
        if not message_id and event in {"message", "agent_message", "message_end"}:
            message_id = _text(payload.get("id"))
        if message_id and "message_id" not in response:
            response["message_id"] = message_id

    if answer_parts:
        response["answer"] = "".join(answer_parts)
    if outputs:
        response["data"] = {"outputs": outputs}
        if not response.get("answer"):
            for key in ("answer", "text", "content", "result", "output"):
                value = _text(outputs.get(key))
                if value:
                    response["answer"] = value
                    break
    if metadata:
        response["metadata"] = metadata
    return response


def _request_dify_json(*, url: str, payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    if _fixed_response_mode(_text(payload.get("response_mode"))) != "streaming":
        return _request_json(url=url, payload=payload, api_key=api_key, timeout=timeout)

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _stream_payload_to_response(_iter_dify_sse_payloads(response))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


_RECORD_CONTAINER_KEYS = (
    "mimirq_records",
    "mimirq_retrieval_records",
    "mimirq_citations",
    "mimirq_evidence",
    "mimirq_contexts",
    "retriever_resources",
    "retrieval_records",
    "records",
    "contexts",
    "citations",
    "evidence",
)
_JSON_RECORD_CONTAINER_KEYS = tuple(f"{key}_json" for key in _RECORD_CONTAINER_KEYS)


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _iter_record_containers(value: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 4:
        return []
    value = _parse_jsonish(value)
    containers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        containers.append(value)
        for child in value.values():
            parsed_child = _parse_jsonish(child)
            if isinstance(parsed_child, dict):
                containers.extend(_iter_record_containers(parsed_child, depth=depth + 1))
    return containers


def _extract_records_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    for container in _iter_record_containers(response):
        if not isinstance(container, dict):
            continue
        for key in (*_RECORD_CONTAINER_KEYS, *_JSON_RECORD_CONTAINER_KEYS):
            raw = _parse_jsonish(container.get(key))
            if isinstance(raw, list):
                return [_normalize_record(item, index) for index, item in enumerate(raw, 1)]
    return []


def _normalize_record(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"title": f"record-{index}", "content": raw, "metadata": {}}
    if not isinstance(raw, dict):
        return {"title": f"record-{index}", "content": "", "metadata": {}}

    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    content = (
        raw.get("content")
        or raw.get("chunk_content")
        or raw.get("text")
        or raw.get("segment")
        or raw.get("snippet")
        or raw.get("document_content")
        or raw.get("page_content")
        or ""
    )
    title = (
        raw.get("title")
        or raw.get("document_name")
        or raw.get("document_title")
        or raw.get("filename")
        or raw.get("dataset_name")
        or f"record-{index}"
    )
    return {
        "title": _text(title),
        "content": _text(content),
        "metadata": dict(metadata),
        "score": raw.get("score") or raw.get("relevance_score") or raw.get("retrieval_score"),
    }


def _normalize_records(raw_records: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_records, list):
        return []
    return [_normalize_record(item, index) for index, item in enumerate(raw_records, 1)]


def _history_source_conversation_id(app: AppSpec, item: dict[str, Any]) -> str:
    conversation_id = _text(item.get("conversation_id") or item.get("dify_conversation_id"))
    if not conversation_id or not app.app_id:
        return ""
    return f"{app.app_id}:{conversation_id}"


def _history_source_run_ids(item: dict[str, Any]) -> list[str]:
    values = [
        _text(item.get("workflow_run_id")),
        _text(item.get("task_id")),
        _text(item.get("source_run_id")),
    ]
    return list(dict.fromkeys(value for value in values if value))


def _history_lookup_result_records(result: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(result, list):
        return _normalize_records(result), {}
    if not isinstance(result, dict):
        return [], {}
    return _normalize_records(result.get("records")), result


def _node_execution_outputs(row: dict[str, Any]) -> dict[str, Any]:
    outputs = row.get("outputs")
    if isinstance(outputs, dict):
        return outputs
    data = row.get("data")
    if isinstance(data, dict) and isinstance(data.get("outputs"), dict):
        return data["outputs"]
    return {}


def _node_execution_title(row: dict[str, Any]) -> str:
    title = _text(row.get("title") or row.get("node_title"))
    if title:
        return title
    data = row.get("data")
    if isinstance(data, dict):
        return _text(data.get("title"))
    return ""


def extract_mimirq_records_from_console_node_executions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("data") if isinstance(payload.get("data"), list) else []
    merge_nodes: list[dict[str, Any]] = []
    convert_nodes: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _node_execution_title(row)
        if "合并知识库知识" in title:
            merge_nodes.append(row)
        elif "MimirQ结果转换" in title:
            convert_nodes.append(row)

    for row in [*merge_nodes, *convert_nodes]:
        outputs = _node_execution_outputs(row)
        for key in ("records_json", "result", "records", "mimirq_records"):
            raw = _parse_jsonish(outputs.get(key))
            records = _normalize_records(raw)
            if records:
                return records
    return []


def lookup_dify_console_mimirq_records(
    *,
    app: AppSpec,
    item: dict[str, Any],
    console_base_url: str,
    console_token: str,
    timeout: float,
) -> dict[str, Any]:
    if not _text(console_token):
        return {"records": [], "source": "dify_console_node_executions", "status": "missing_console_token"}
    message_id = _text(item.get("message_id"))
    if not message_id:
        return {"records": [], "source": "dify_console_node_executions", "status": "missing_message_id"}

    try:
        from scripts.changzhou_gov_dify_workflow_sync import _request_json as _console_request_json

        message = _console_request_json(
            console_base_url=console_base_url,
            console_token=console_token,
            path=f"/apps/{app.app_id}/messages/{message_id}",
            timeout=timeout,
        )
        workflow_run_id = _text(message.get("workflow_run_id")) or _text(item.get("workflow_run_id"))
        if not workflow_run_id:
            return {"records": [], "source": "dify_console_node_executions", "status": "missing_workflow_run_id"}

        executions = _console_request_json(
            console_base_url=console_base_url,
            console_token=console_token,
            path=f"/apps/{app.app_id}/workflow-runs/{workflow_run_id}/node-executions",
            timeout=timeout,
        )
        records = extract_mimirq_records_from_console_node_executions(executions)
        return {
            "records": records,
            "source": "dify_console_node_executions",
            "status": "found" if records else "not_found",
            "workflow_run_id": workflow_run_id,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "records": [],
            "source": "dify_console_node_executions",
            "status": "error",
            "error": str(exc)[:400],
        }


def _query_mimirq_history_records_once(
    *,
    app: AppSpec,
    item: dict[str, Any],
    require_run_id: bool,
) -> list[dict[str, Any]]:
    from sqlalchemy import or_

    from app.core.database import SessionLocal
    from app.models.chat import Message

    source_conversation_id = _history_source_conversation_id(app, item)
    if not source_conversation_id:
        return []

    run_ids = _history_source_run_ids(item)
    db = SessionLocal()
    try:
        external = Message.message_metadata["external_conversation"]  # type: ignore[index]
        query = (
            db.query(Message)
            .filter(
                Message.role == "assistant",
                external["source"].astext == "dify",
                external["source_conversation_id"].astext == source_conversation_id,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
        )
        if run_ids:
            run_filters = [external["source_run_id"].astext.in_(run_ids)]
            run_filters.extend(external["source_message_id"].astext.like(f"{run_id}:%") for run_id in run_ids)
            query = query.filter(or_(*run_filters))
        elif require_run_id:
            return []

        for message in query.limit(20).all():
            citations = getattr(message, "citations", None)
            records = _normalize_records(citations)
            if records:
                return records
    finally:
        db.close()
    return []


def lookup_mimirq_history_records(
    *,
    app: AppSpec,
    item: dict[str, Any],
    wait_sec: float,
    poll_sec: float,
) -> dict[str, Any]:
    source_conversation_id = _history_source_conversation_id(app, item)
    if not source_conversation_id:
        return {"records": [], "source": "mimirq_history", "status": "missing_conversation_id"}

    deadline = time.monotonic() + max(0.0, float(wait_sec or 0.0))
    poll_interval = max(0.05, min(float(poll_sec or 0.5), 5.0))
    last_error = ""
    while True:
        try:
            records = _query_mimirq_history_records_once(app=app, item=item, require_run_id=True)
            if not records:
                records = _query_mimirq_history_records_once(app=app, item=item, require_run_id=False)
            if records:
                return {
                    "records": records,
                    "source": "mimirq_history",
                    "status": "found",
                    "source_conversation_id": source_conversation_id,
                    "source_run_ids": _history_source_run_ids(item),
                }
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:400]
            break

        if time.monotonic() >= deadline:
            break
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    out: dict[str, Any] = {
        "records": [],
        "source": "mimirq_history",
        "status": "not_found",
        "source_conversation_id": source_conversation_id,
        "source_run_ids": _history_source_run_ids(item),
    }
    if last_error:
        out["error"] = last_error
    return out


def _read_key_file(path: str) -> dict[str, str]:
    key_path = Path(path)
    if not key_path.is_file():
        return {}
    payload = json.loads(key_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            out[_text(key)] = _text(value)
        elif isinstance(value, dict):
            for candidate in ("api_key", "token", "key"):
                if _text(value.get(candidate)):
                    out[_text(key)] = _text(value.get(candidate))
                    break
    return out


def _read_app_config_file(path: str) -> dict[str, dict[str, str]]:
    key_path = Path(path)
    if not key_path.is_file():
        return {}
    payload = json.loads(key_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        config: dict[str, str] = {}
        for field in ("mode", "description", "kind"):
            if _text(value.get(field)):
                config[field] = _text(value.get(field))
        if config:
            out[_text(key)] = config
    return out


def _env_file_values(path: str) -> dict[str, str]:
    env_path = Path(_text(path))
    if not env_path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_mimirq_token(explicit_token: str, *, env_file: str = ".env") -> str:
    explicit = _text(explicit_token)
    if explicit:
        return explicit
    env_token = _text(os.getenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEY"))
    if env_token:
        return env_token
    env_tokens = _text(os.getenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"))
    if env_tokens:
        return _text(env_tokens.split(",", 1)[0])
    values = _env_file_values(env_file)
    file_token = _text(values.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEY"))
    if file_token:
        return file_token
    file_tokens = _text(values.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"))
    if file_tokens:
        return _text(file_tokens.split(",", 1)[0])
    return ""


def load_app_specs(raw_specs: list[str], key_file: str) -> list[AppSpec]:
    key_map = _read_key_file(key_file) if key_file else {}
    config_map = _read_app_config_file(key_file) if key_file else {}
    specs: list[dict[str, Any]]
    if raw_specs:
        specs = []
        for raw in raw_specs:
            parts = raw.split(":")
            if len(parts) < 4:
                raise ValueError("--app must be label:app_id:kind:api_key_or_key_name[:mode]")
            label, app_id, kind, key_ref = parts[:4]
            mode = parts[4] if len(parts) > 4 else "chat"
            specs.append(
                {
                    "label": label,
                    "app_id": app_id,
                    "kind": kind,
                    "description": kind,
                    "api_key": key_map.get(key_ref, key_ref),
                    "mode": mode,
                }
            )
    else:
        specs = []
        for item in DEFAULT_APP_SPECS:
            config = config_map.get(item["label"]) or config_map.get(item["app_id"]) or {}
            specs.append(
                {
                    **item,
                    **config,
                    "api_key": key_map.get(item["label"]) or key_map.get(item["app_id"]) or "",
                }
            )

    return [
        AppSpec(
            label=_text(item.get("label")),
            app_id=_text(item.get("app_id")),
            kind=_text(item.get("kind")),
            description=_text(item.get("description")),
            api_key=_text(item.get("api_key")),
            mode=_fixed_mode(_text(item.get("mode") or "chat")),
        )
        for item in specs
        if _text(item.get("label")) and _text(item.get("app_id"))
    ]


def build_key_requirements(apps: list[AppSpec]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    template: dict[str, dict[str, str]] = {}
    for app in apps:
        accepted_keys = [app.label, app.app_id]
        rows.append(
            {
                "label": app.label,
                "app_id": app.app_id,
                "kind": app.kind,
                "description": app.description,
                "mode": _fixed_mode(app.mode),
                "key_present": bool(app.api_key),
                "accepted_keys": accepted_keys,
                "workflow_url": f"https://dify.example.com:3000/brainai/app/{app.app_id}/workflow",
            }
        )
        template[app.label] = {"api_key": "app-xxx", "mode": "auto"}
    missing = [row["label"] for row in rows if not row["key_present"]]
    return {
        "schema": "mimirq.dify_3way_benchmark.key_requirements.v1",
        "generated_at": _utc_now_text(),
        "summary": {
            "apps": len(rows),
            "missing_api_keys": len(missing),
            "ready": not missing,
            "missing_labels": missing,
        },
        "apps": rows,
        "template": template,
        "usage": {
            "path_example": "/tmp/dify_3way_app_keys.json",
            "preflight_command": "python scripts/dify_3way_benchmark.py --out-dir artifacts/dify_3way_benchmark_remote_preflight --target-count 800 --limit 1 --app-key-file /tmp/dify_3way_app_keys.json --auto-mode --timeout 60 --preflight",
            "full_command": "python scripts/dify_3way_benchmark.py --out-dir artifacts/dify_3way_benchmark_remote_full --target-count 800 --app-key-file /tmp/dify_3way_app_keys.json --auto-mode --concurrency 3 --timeout 180 --resume --write-bundle --strict-complete",
        },
    }


def resolve_app_modes(
    *,
    apps: list[AppSpec],
    probe_case: dict[str, Any],
    base_url: str,
    timeout: float,
    workflow_query_key: str,
    user_prefix: str,
    response_mode: str = "blocking",
    force: bool = False,
    probe_fn: Any | None = None,
) -> tuple[list[AppSpec], dict[str, Any]]:
    probe = probe_fn or _call_case
    resolved: list[AppSpec] = []
    items: list[dict[str, Any]] = []
    for app in apps:
        should_probe = bool(force or app.mode == "auto")
        item: dict[str, Any] = {
            "system": app.label,
            "app_id": app.app_id,
            "original_mode": app.mode,
            "selected_mode": app.mode,
            "key_present": bool(app.api_key),
            "probed": False,
            "attempts": [],
        }
        if not should_probe:
            selected = replace(app, mode=_fixed_mode(app.mode))
            item["selected_mode"] = selected.mode
            item["selected_endpoint"] = _endpoint_url(base_url, selected.mode)
            resolved.append(selected)
            items.append(item)
            continue
        if not app.api_key:
            selected = replace(app, mode="chat" if app.mode == "auto" else _fixed_mode(app.mode))
            item.update({"selected_mode": selected.mode, "selected_endpoint": _endpoint_url(base_url, selected.mode), "status": "missing_api_key"})
            resolved.append(selected)
            items.append(item)
            continue

        selected_mode = ""
        for mode in ("chat", "workflow"):
            probe_app = replace(app, mode=mode)
            result = probe(
                app=probe_app,
                case=probe_case,
                base_url=base_url,
                timeout=timeout,
                response_mode=response_mode,
                workflow_query_key=workflow_query_key,
                user_prefix=f"{user_prefix}-mode-probe",
            )
            attempt = {
                "mode": mode,
                "endpoint": _endpoint_url(base_url, mode),
                "ok": result.get("ok") is True if isinstance(result, dict) else False,
            }
            if isinstance(result, dict) and result.get("error"):
                attempt["error"] = _safe_error(result.get("error"), secrets=[app.api_key])
            item["attempts"].append(attempt)
            if attempt["ok"]:
                selected_mode = mode
                break
        selected = replace(app, mode=selected_mode or "chat")
        item.update(
            {
                "probed": True,
                "selected_mode": selected.mode,
                "selected_endpoint": _endpoint_url(base_url, selected.mode),
                "status": "ok" if selected_mode else "failed",
            }
        )
        resolved.append(selected)
        items.append(item)
    return resolved, {
        "schema": "mimirq.dify_3way_benchmark.mode_resolution.v1",
        "generated_at": _utc_now_text(),
        "base_url": base_url.rstrip("/"),
        "summary": {
            "apps": len(apps),
            "probed": sum(1 for item in items if item.get("probed") is True),
            "ok": sum(1 for item in items if item.get("status") == "ok"),
            "failed": sum(1 for item in items if item.get("status") == "failed"),
            "missing_api_key": sum(1 for item in items if item.get("status") == "missing_api_key"),
        },
        "items": items,
    }


def _call_case(
    *,
    app: AppSpec,
    case: dict[str, Any],
    base_url: str,
    timeout: float,
    workflow_query_key: str,
    user_prefix: str,
    response_mode: str = "blocking",
    request_json_fn: Any | None = None,
    history_records_fn: Any | None = None,
    console_records_fn: Any | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    item: dict[str, Any] = {
        "id": _case_id(case),
        "case_id": _case_id(case),
        "source_case_id": _text(case.get("source_case_id")),
        "query": _case_question(case),
        "app_id": app.app_id,
        "system": app.label,
        "records": [],
        "answer": "",
        "ok": False,
    }
    try:
        payload = build_dify_payload(
            case,
            mode=app.mode,
            user=f"{user_prefix}-{app.label}",
            response_mode=_fixed_response_mode(response_mode),
            workflow_query_key=workflow_query_key,
        )
        request_json = request_json_fn or _request_dify_json
        response = request_json(url=_endpoint_url(base_url, app.mode), payload=payload, api_key=app.api_key, timeout=timeout)
        item["answer"] = extract_dify_answer(response)
        item["records"] = _extract_records_from_response(response)
        item.update(extract_dify_response_refs(response))
        if not item["records"] and app.kind == "http_to_mimirq" and history_records_fn is not None:
            lookup_result = history_records_fn(app=app, item=item, timeout=timeout)
            history_records, history_meta = _history_lookup_result_records(lookup_result)
            if history_records:
                item["records"] = history_records
                item["record_source"] = _text(history_meta.get("source")) or "mimirq_history"
                item["record_backfill_status"] = _text(history_meta.get("status")) or "found"
            else:
                item["record_backfill_status"] = _text(history_meta.get("status")) or "not_found"
            if history_meta.get("error"):
                item["record_backfill_error"] = _safe_error(history_meta.get("error"), secrets=[app.api_key])
        if not item["records"] and app.kind == "http_to_mimirq" and console_records_fn is not None:
            lookup_result = console_records_fn(app=app, item=item, timeout=timeout)
            console_records, console_meta = _history_lookup_result_records(lookup_result)
            if console_records:
                item["records"] = console_records
                item["record_source"] = _text(console_meta.get("source")) or "dify_console_node_executions"
                item["console_record_backfill_status"] = _text(console_meta.get("status")) or "found"
            else:
                item["console_record_backfill_status"] = _text(console_meta.get("status")) or "not_found"
            if console_meta.get("workflow_run_id"):
                item["workflow_run_id"] = _text(console_meta.get("workflow_run_id"))
            if console_meta.get("error"):
                item["console_record_backfill_error"] = _safe_error(console_meta.get("error"), secrets=[app.api_key])
        item["ok"] = bool(item["answer"])
        if not item["ok"]:
            item["error"] = "empty answer"
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:1200]
        item["error"] = error
        item.update(diagnose_dify_error(error))
    item["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return item


def _post_json_no_proxy(url: str, api_key: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def _call_mimirq_case(
    *,
    case: dict[str, Any],
    base_url: str,
    token: str,
    timeout: float,
    retrieval_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    case_id = _case_id(case)
    item: dict[str, Any] = {
        "id": case_id,
        "case_id": case_id,
        "source_case_id": _text(case.get("source_case_id")),
        "query": _case_question(case),
        "system": "mimirq_direct",
        "records": [],
        "answer": "",
        "ok": False,
    }
    try:
        payload = {
            "knowledge_id": _text(case.get("knowledge_id")) or "changzhou_city_service",
            "query": _case_question(case),
            "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
            "request_id": f"dify-3way-direct-{case_id}",
            "dify_conversation_id": "dify-3way-direct",
            "dify_message_id": f"dify-3way-direct-msg-{case_id}",
            "dify_workflow_run_id": "dify-3way-direct-run",
        }
        if isinstance(retrieval_overrides, dict):
            payload["retrieval_setting"].update(
                {str(key): value for key, value in retrieval_overrides.items()}
            )
        response = _post_json_no_proxy(
            f"{base_url.rstrip('/')}/api/v1/integrations/dify/retrieval",
            token,
            payload,
            timeout=timeout,
        )
        records = [_normalize_record(record, index) for index, record in enumerate(response.get("records") or [], 1)]
        item["records"] = records
        item["answer"] = "\n".join(_text(record.get("content")) for record in records[:3] if _text(record.get("content")))
        item["ok"] = bool(records)
    except Exception as exc:  # noqa: BLE001
        item["error"] = str(exc)[:1200]
    item["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return item


def _case_ids(cases: list[dict[str, Any]]) -> set[str]:
    return {_case_id(case) for case in cases if _case_id(case)}


def _items_by_case_id(items: list[dict[str, Any]], valid_case_ids: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        case_id = _text(item.get("case_id") or item.get("id"))
        if case_id and case_id in valid_case_ids:
            out[case_id] = dict(item)
    return out


def _run_item_sort_key(item: dict[str, Any]) -> str:
    return _text(item.get("case_id") or item.get("id"))


def _safe_error(message: Any, *, secrets: list[str]) -> str:
    text = _text(message)[:1200]
    for secret in secrets:
        secret_text = _text(secret)
        if secret_text:
            text = text.replace(secret_text, "<redacted>")
    return text


def _is_timeout_error_text(value: Any) -> bool:
    text = _text(value).lower()
    return any(marker in text for marker in ("timed out", "time-out", "timeout", "readtimeout", "http 504"))


def _retry_timeout_seconds(timeout: float) -> float:
    base = float(timeout or 0.0)
    return min(max(base * TIMEOUT_RETRY_MULTIPLIER, base + TIMEOUT_RETRY_MIN_ADD_SEC), TIMEOUT_RETRY_MAX_SEC)


def _execution_stats(
    items: list[dict[str, Any]],
    *,
    executed_case_ids: set[str],
    concurrency: int,
    elapsed_ms: int,
) -> dict[str, Any]:
    executed = [item for item in items if _text(item.get("case_id") or item.get("id")) in executed_case_ids]
    latencies = [
        int(round(float(item.get("total_latency_ms", item.get("latency_ms")))))
        for item in executed
        if item.get("total_latency_ms", item.get("latency_ms")) is not None
    ]
    return {
        "concurrency": max(1, int(concurrency)),
        "cases": len(executed),
        "elapsed_ms": max(0, int(elapsed_ms)),
        "throughput_cases_per_sec": round(throughput_per_sec(count=len(executed), elapsed_ms=elapsed_ms), 6),
        "latency_ms": summarize_latencies_ms(latencies),
    }


def _merge_items_by_case_id(items: list[dict[str, Any]], replacements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {_text(item.get("case_id") or item.get("id")): dict(item) for item in items if _text(item.get("case_id") or item.get("id"))}
    for item in replacements:
        key = _text(item.get("case_id") or item.get("id"))
        if key:
            merged[key] = dict(item)
    return sorted(merged.values(), key=_run_item_sort_key)


def _merge_retry_results(
    items: list[dict[str, Any]],
    replacements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_by_id = {
        _text(item.get("case_id") or item.get("id")): item
        for item in items
        if _text(item.get("case_id") or item.get("id"))
    }
    enriched: list[dict[str, Any]] = []
    for replacement in replacements:
        current = dict(replacement)
        key = _text(current.get("case_id") or current.get("id"))
        previous = previous_by_id.get(key, {})
        attempt_latencies = [float(value) for value in previous.get("attempt_latency_ms") or []]
        if not attempt_latencies and previous.get("latency_ms") is not None:
            attempt_latencies.append(float(previous["latency_ms"]))
        if current.get("latency_ms") is not None:
            attempt_latencies.append(float(current["latency_ms"]))
        if attempt_latencies:
            current["attempt_count"] = len(attempt_latencies)
            current["attempt_latency_ms"] = attempt_latencies
            current["total_latency_ms"] = round(sum(attempt_latencies), 2)
        enriched.append(current)
    return _merge_items_by_case_id(items, enriched)


def _pending_cases(
    cases: list[dict[str, Any]],
    existing_items: list[dict[str, Any]] | None,
    *,
    retry_failures: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing_by_id = _items_by_case_id(existing_items or [], _case_ids(cases))
    reusable: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for case in cases:
        case_id = _case_id(case)
        existing = existing_by_id.get(case_id)
        if existing is None:
            pending.append(case)
            continue
        if retry_failures and existing.get("ok") is not True:
            pending.append(case)
            continue
        reusable.append(existing)
    return pending, reusable


def _load_existing_run_items(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else []
    return [dict(item) for item in items if isinstance(item, dict)]


def _load_run_file(path: Path, *, system: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    run = dict(payload)
    run["system"] = _text(run.get("system")) or system
    return run


def load_report_only_runs(*, out_dir: Path, apps: list[AppSpec], include_mimirq_direct: bool) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if include_mimirq_direct:
        run = _load_run_file(out_dir / "run_mimirq_direct.json", system="mimirq_direct")
        if run is not None:
            runs.append(run)
    for app in apps:
        run = _load_run_file(out_dir / f"run_{app.label}.json", system=app.label)
        if run is not None:
            runs.append(run)
    return runs


def _failure_reasons(items: list[dict[str, Any]]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for item in items:
        if item.get("ok") is True:
            continue
        reason = _text(item.get("error")) or "unknown"
        if "timed out" in reason.lower():
            reason = "timed_out"
        elif reason.startswith("HTTP "):
            reason = reason.split(":", 1)[0]
        reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _missing_key_run_from_existing(
    *,
    system: str,
    app_payload: dict[str, Any],
    cases: list[dict[str, Any]],
    existing_items: list[dict[str, Any]] | None,
    retry_failures: bool,
    reason: str,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending, reusable = _pending_cases(cases, existing_items, retry_failures=retry_failures)
    items = sorted(reusable, key=_run_item_sort_key)
    succeeded = sum(1 for item in items if item.get("ok") is True)
    complete_from_cache = bool(items) and not pending
    summary: dict[str, Any] = {
        "cases": len(cases),
        "succeeded": succeeded,
        "failed": len(cases) - succeeded,
        "resumed": len(items),
        "executed": 0,
        "pending": len(pending),
        "failure_reasons": _failure_reasons(items),
        "reason": reason,
        "reused_without_key": complete_from_cache,
    }
    if not complete_from_cache:
        summary["skipped"] = True
    out: dict[str, Any] = {
        "schema": "mimirq.dify_3way_benchmark.run.v1",
        "generated_at": _utc_now_text(),
        "system": system,
        "app": app_payload,
        "summary": summary,
        "items": items,
    }
    if source:
        out["source"] = source
    return out


def run_preflight(
    *,
    apps: list[AppSpec],
    cases: list[dict[str, Any]],
    base_url: str,
    timeout: float,
    workflow_query_key: str,
    user_prefix: str,
    response_mode: str = "blocking",
    http_history_backfill: bool = True,
    history_backfill_wait_sec: float = 3.0,
    history_backfill_poll_sec: float = 0.5,
    console_base_url: str = "",
    console_token: str = "",
    console_backfill: bool = True,
) -> dict[str, Any]:
    probe_case = cases[0] if cases else {}
    items: list[dict[str, Any]] = []
    for app in apps:
        endpoint = _endpoint_url(base_url, app.mode)
        item: dict[str, Any] = {
            "system": app.label,
            "app_id": app.app_id,
            "kind": app.kind,
            "mode": app.mode,
            "endpoint": endpoint,
            "case_id": _case_id(probe_case),
            "key_present": bool(app.api_key),
            "ok": False,
        }
        if not app.api_key:
            item["status"] = "missing_api_key"
            items.append(item)
            continue
        result = _call_case(
            app=app,
            case=probe_case,
            base_url=base_url,
            timeout=timeout,
            response_mode=response_mode,
            workflow_query_key=workflow_query_key,
            user_prefix=f"{user_prefix}-preflight",
            history_records_fn=(
                (lambda *, app, item, **_kwargs: lookup_mimirq_history_records(
                    app=app,
                    item=item,
                    wait_sec=history_backfill_wait_sec,
                    poll_sec=history_backfill_poll_sec,
                ))
                if http_history_backfill and app.kind == "http_to_mimirq"
                else None
            ),
            console_records_fn=(
                (lambda *, app, item, timeout, **_kwargs: lookup_dify_console_mimirq_records(
                    app=app,
                    item=item,
                    console_base_url=console_base_url,
                    console_token=console_token,
                    timeout=timeout,
                ))
                if console_backfill and _text(console_token) and app.kind == "http_to_mimirq"
                else None
            ),
        )
        item.update(
            {
                "ok": result.get("ok") is True,
                "status": "ok" if result.get("ok") is True else "failed",
                "latency_ms": result.get("latency_ms"),
                "answer_chars": len(_text(result.get("answer"))),
                "records": len(result.get("records") if isinstance(result.get("records"), list) else []),
            }
        )
        if result.get("error"):
            item["error"] = _safe_error(result.get("error"), secrets=[app.api_key])
        items.append(item)

    return {
        "schema": "mimirq.dify_3way_benchmark.preflight.v1",
        "generated_at": _utc_now_text(),
        "base_url": base_url.rstrip("/"),
        "case": {
            "case_id": _case_id(probe_case),
            "query": _case_question(probe_case),
            "knowledge_id": _text(probe_case.get("knowledge_id")),
        },
        "summary": {
            "apps": len(apps),
            "ok": sum(1 for item in items if item.get("ok") is True),
            "missing_api_key": sum(1 for item in items if item.get("status") == "missing_api_key"),
            "failed": sum(1 for item in items if item.get("status") == "failed"),
            "all_ready": bool(items) and all(item.get("ok") is True for item in items),
        },
        "items": items,
    }


def run_app(
    *,
    app: AppSpec,
    cases: list[dict[str, Any]],
    base_url: str,
    timeout: float,
    concurrency: int,
    workflow_query_key: str,
    user_prefix: str,
    response_mode: str = "blocking",
    existing_items: list[dict[str, Any]] | None = None,
    retry_failures: bool = False,
    run_path: Path | None = None,
    flush_every: int = 50,
    http_history_backfill: bool = True,
    history_backfill_wait_sec: float = 3.0,
    history_backfill_poll_sec: float = 0.5,
    console_base_url: str = "",
    console_token: str = "",
    console_backfill: bool = True,
) -> dict[str, Any]:
    if not app.api_key:
        return _missing_key_run_from_existing(
            system=app.label,
            app_payload={k: getattr(app, k) for k in ("label", "app_id", "kind", "description", "mode")},
            cases=cases,
            existing_items=existing_items,
            retry_failures=retry_failures,
            reason="missing_api_key",
            source={"provider": "dify", "base_url": base_url.rstrip("/"), "endpoint": _endpoint_url(base_url, app.mode)},
        )

    pending, reusable = _pending_cases(cases, existing_items, retry_failures=retry_failures)
    items: list[dict[str, Any]] = list(reusable)
    executed_case_ids = {_case_id(case) for case in pending}
    run_started = time.perf_counter()
    history_records_fn = (
        (lambda *, app, item, **_kwargs: lookup_mimirq_history_records(
            app=app,
            item=item,
            wait_sec=history_backfill_wait_sec,
            poll_sec=history_backfill_poll_sec,
        ))
        if http_history_backfill and app.kind == "http_to_mimirq"
        else None
    )
    console_records_fn = (
        (lambda *, app, item, timeout, **_kwargs: lookup_dify_console_mimirq_records(
            app=app,
            item=item,
            console_base_url=console_base_url,
            console_token=console_token,
            timeout=timeout,
        ))
        if console_backfill and _text(console_token) and app.kind == "http_to_mimirq"
        else None
    )

    def snapshot() -> None:
        if run_path is None:
            return
        ordered_items = sorted(items, key=_run_item_sort_key)
        succeeded = sum(1 for item in ordered_items if item.get("ok") is True)
        _write_json(
            run_path,
            {
                "schema": "mimirq.dify_3way_benchmark.run.v1",
                "generated_at": _utc_now_text(),
                "system": app.label,
                "app": {k: getattr(app, k) for k in ("label", "app_id", "kind", "description", "mode")},
                "source": {"provider": "dify", "base_url": base_url.rstrip("/"), "endpoint": _endpoint_url(base_url, app.mode)},
                "execution": _execution_stats(
                    ordered_items,
                    executed_case_ids=executed_case_ids,
                    concurrency=concurrency,
                    elapsed_ms=int((time.perf_counter() - run_started) * 1000),
                ),
                "summary": {
                    "cases": len(cases),
                    "succeeded": succeeded,
                    "failed": len(ordered_items) - succeeded,
                    "resumed": len(reusable),
                    "executed": len(ordered_items) - len(reusable),
                    "pending": max(0, len(cases) - len(ordered_items)),
                    "partial": len(ordered_items) < len(cases),
                    "failure_reasons": _failure_reasons(ordered_items),
                },
                "items": ordered_items,
            },
        )

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [
            executor.submit(
                _call_case,
                app=app,
                case=case,
                base_url=base_url,
                timeout=timeout,
                response_mode=response_mode,
                workflow_query_key=workflow_query_key,
                user_prefix=user_prefix,
                history_records_fn=history_records_fn,
                console_records_fn=console_records_fn,
            )
            for case in pending
        ]
        for future in as_completed(futures):
            items.append(future.result())
            if len(items) % 50 == 0:
                ok = sum(1 for item in items if item.get("ok") is True)
                print(f"[{app.label}] progress={len(items)}/{len(cases)} ok={ok}", flush=True)
            if run_path is not None and int(flush_every or 0) > 0 and len(items) % int(flush_every) == 0:
                snapshot()

    timeout_case_ids = {
        _text(item.get("case_id") or item.get("id"))
        for item in items
        if item.get("ok") is not True and _is_timeout_error_text(item.get("error"))
    }
    if timeout_case_ids:
        retry_cases = [case for case in pending if _case_id(case) in timeout_case_ids]
        retry_timeout = _retry_timeout_seconds(timeout)
        if retry_cases:
            print(
                f"[{app.label}] retrying {len(retry_cases)} timed out cases with timeout={retry_timeout:.1f}s",
                flush=True,
            )
            retry_results: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(retry_cases)))) as executor:
                futures = [
                    executor.submit(
                        _call_case,
                        app=app,
                        case=case,
                        base_url=base_url,
                        timeout=retry_timeout,
                        response_mode=response_mode,
                        workflow_query_key=workflow_query_key,
                        user_prefix=user_prefix,
                        history_records_fn=history_records_fn,
                        console_records_fn=console_records_fn,
                    )
                    for case in retry_cases
                ]
                for future in as_completed(futures):
                    retry_results.append(future.result())
            items = _merge_retry_results(items, retry_results)
            if run_path is not None:
                snapshot()

    items.sort(key=_run_item_sort_key)
    succeeded = sum(1 for item in items if item.get("ok") is True)
    return {
        "schema": "mimirq.dify_3way_benchmark.run.v1",
        "generated_at": _utc_now_text(),
        "system": app.label,
        "app": {k: getattr(app, k) for k in ("label", "app_id", "kind", "description", "mode")},
        "source": {"provider": "dify", "base_url": base_url.rstrip("/"), "endpoint": _endpoint_url(base_url, app.mode)},
        "execution": _execution_stats(
            items,
            executed_case_ids=executed_case_ids,
            concurrency=concurrency,
            elapsed_ms=int((time.perf_counter() - run_started) * 1000),
        ),
        "summary": {
            "cases": len(cases),
            "succeeded": succeeded,
            "failed": len(cases) - succeeded,
            "resumed": len(reusable),
            "executed": len(pending),
            "failure_reasons": _failure_reasons(items),
        },
        "items": items,
    }


def run_mimirq_direct(
    *,
    cases: list[dict[str, Any]],
    base_url: str,
    token: str,
    timeout: float,
    concurrency: int,
    retrieval_overrides: dict[str, Any] | None = None,
    existing_items: list[dict[str, Any]] | None = None,
    retry_failures: bool = False,
    run_path: Path | None = None,
    flush_every: int = 50,
) -> dict[str, Any]:
    if not token:
        return _missing_key_run_from_existing(
            system="mimirq_direct",
            app_payload={"label": "mimirq_direct", "app_id": "local", "kind": "direct_external_knowledge", "mode": "retrieval"},
            cases=cases,
            existing_items=existing_items,
            retry_failures=retry_failures,
            reason="missing_mimirq_token",
            source={"provider": "mimirq", "base_url": base_url.rstrip("/"), "endpoint": f"{base_url.rstrip('/')}/api/v1/integrations/dify/retrieval"},
        )

    pending, reusable = _pending_cases(cases, existing_items, retry_failures=retry_failures)
    items: list[dict[str, Any]] = list(reusable)
    executed_case_ids = {_case_id(case) for case in pending}
    run_started = time.perf_counter()

    def snapshot() -> None:
        if run_path is None:
            return
        ordered_items = sorted(items, key=_run_item_sort_key)
        succeeded = sum(1 for item in ordered_items if item.get("ok") is True)
        _write_json(
            run_path,
            {
                "schema": "mimirq.dify_3way_benchmark.run.v1",
                "generated_at": _utc_now_text(),
                "system": "mimirq_direct",
                "app": {"label": "mimirq_direct", "app_id": "local", "kind": "direct_external_knowledge", "mode": "retrieval"},
                "source": {"provider": "mimirq", "base_url": base_url.rstrip("/"), "endpoint": f"{base_url.rstrip('/')}/api/v1/integrations/dify/retrieval"},
                "execution": _execution_stats(
                    ordered_items,
                    executed_case_ids=executed_case_ids,
                    concurrency=concurrency,
                    elapsed_ms=int((time.perf_counter() - run_started) * 1000),
                ),
                "summary": {
                    "cases": len(cases),
                    "succeeded": succeeded,
                    "failed": len(ordered_items) - succeeded,
                    "resumed": len(reusable),
                    "executed": len(ordered_items) - len(reusable),
                    "pending": max(0, len(cases) - len(ordered_items)),
                    "partial": len(ordered_items) < len(cases),
                    "failure_reasons": _failure_reasons(ordered_items),
                },
                "items": ordered_items,
            },
        )

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [
            executor.submit(
                _call_mimirq_case,
                case=case,
                base_url=base_url,
                token=token,
                timeout=timeout,
                retrieval_overrides=retrieval_overrides,
            )
            for case in pending
        ]
        for future in as_completed(futures):
            items.append(future.result())
            if len(items) % 50 == 0:
                ok = sum(1 for item in items if item.get("ok") is True)
                print(f"[mimirq_direct] progress={len(items)}/{len(cases)} ok={ok}", flush=True)
            if run_path is not None and int(flush_every or 0) > 0 and len(items) % int(flush_every) == 0:
                snapshot()

    timeout_case_ids = {
        _text(item.get("case_id") or item.get("id"))
        for item in items
        if item.get("ok") is not True and _is_timeout_error_text(item.get("error"))
    }
    if timeout_case_ids:
        retry_cases = [case for case in pending if _case_id(case) in timeout_case_ids]
        retry_timeout = _retry_timeout_seconds(timeout)
        if retry_cases:
            print(
                f"[mimirq_direct] retrying {len(retry_cases)} timed out cases with timeout={retry_timeout:.1f}s",
                flush=True,
            )
            retry_results: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(retry_cases)))) as executor:
                futures = [
                    executor.submit(
                        _call_mimirq_case,
                        case=case,
                        base_url=base_url,
                        token=token,
                        timeout=retry_timeout,
                        retrieval_overrides=retrieval_overrides,
                    )
                    for case in retry_cases
                ]
                for future in as_completed(futures):
                    retry_results.append(future.result())
            items = _merge_retry_results(items, retry_results)
            if run_path is not None:
                snapshot()

    items.sort(key=_run_item_sort_key)
    succeeded = sum(1 for item in items if item.get("ok") is True)
    return {
        "schema": "mimirq.dify_3way_benchmark.run.v1",
        "generated_at": _utc_now_text(),
        "system": "mimirq_direct",
        "app": {"label": "mimirq_direct", "app_id": "local", "kind": "direct_external_knowledge", "mode": "retrieval"},
        "source": {"provider": "mimirq", "base_url": base_url.rstrip("/"), "endpoint": f"{base_url.rstrip('/')}/api/v1/integrations/dify/retrieval"},
        "execution": _execution_stats(
            items,
            executed_case_ids=executed_case_ids,
            concurrency=concurrency,
            elapsed_ms=int((time.perf_counter() - run_started) * 1000),
        ),
        "summary": {
            "cases": len(cases),
            "succeeded": succeeded,
            "failed": len(cases) - succeeded,
            "resumed": len(reusable),
            "executed": len(pending),
            "failure_reasons": _failure_reasons(items),
        },
        "items": items,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_value(value: Any) -> str:
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _text(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_manifest(*, out_dir: Path, report: dict[str, Any], apps: list[AppSpec], include_mimirq_direct: bool) -> dict[str, Any]:
    filenames = [
        "cases_800.json",
        "truth_manifest.json",
        "apps.json",
        "key_requirements.json",
        "mode_resolution_report.json",
        "comparison_report.json",
        "comparison_report.md",
        "summary_for_sharing.md",
        "audit_review.jsonl",
        "audit_review.csv",
    ]
    if include_mimirq_direct:
        filenames.append("run_mimirq_direct.json")
    filenames.extend(f"run_{app.label}.json" for app in apps)

    files: list[dict[str, Any]] = []
    for filename in filenames:
        path = out_dir / filename
        if not path.is_file():
            continue
        files.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return {
        "schema": "mimirq.dify_3way_benchmark.artifact_manifest.v1",
        "generated_at": _utc_now_text(),
        "out_dir": str(out_dir),
        "complete_3way_800": (report.get("completion_status") or {}).get("complete_3way_800"),
        "files": files,
    }


def write_artifact_bundle(*, out_dir: Path, manifest: dict[str, Any], bundle_name: str = "dify_3way_benchmark_bundle.zip") -> Path:
    out_dir = out_dir.resolve()
    bundle_path = out_dir / bundle_name
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    paths: list[Path] = [out_dir / "artifact_manifest.json"]
    for item in files:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        if isinstance(raw_path, str) and raw_path:
            paths.append(Path(raw_path))

    seen_arcnames: set[str] = set()
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_absolute():
                path = path.resolve()
            else:
                cwd_relative = path.resolve()
                out_dir_relative = (out_dir / path).resolve()
                path = cwd_relative if cwd_relative.is_file() else out_dir_relative
            if not path.is_file() or path == bundle_path:
                continue
            try:
                arcname = path.relative_to(out_dir).as_posix()
            except ValueError:
                continue
            if arcname in seen_arcnames:
                continue
            seen_arcnames.add(arcname)
            archive.write(path, arcname)
    return bundle_path


def _preview(value: Any, limit: int = 320) -> str:
    text = " ".join(_text(value).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _metric_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key)
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _business_score(row: dict[str, Any]) -> float:
    return round(
        _metric_float(row, "answer_clause_coverage") * 0.35
        + _metric_float(row, "answer_subquestion_coverage") * 0.25
        + _metric_float(row, "evidence_coverage") * 0.2
        + _metric_float(row, "answer_supported_clause_rate") * 0.15
        + (1.0 - _metric_float(row, "wrong_evidence_rate")) * 0.05,
        6,
    )


def _business_score_system(row: dict[str, Any]) -> float:
    return round(
        _metric_float(row, "mean_answer_clause_coverage") * 0.35
        + _metric_float(row, "mean_answer_subquestion_coverage") * 0.25
        + _metric_float(row, "mean_evidence_coverage") * 0.2
        + _metric_float(row, "mean_answer_supported_clause_rate") * 0.15
        + (1.0 - _metric_float(row, "mean_wrong_evidence_rate")) * 0.05,
        6,
    )


def _audit_verdict(score_item: dict[str, Any], raw_item: dict[str, Any]) -> str:
    answer = _text(raw_item.get("answer"))
    answer_clause = _metric_float(score_item, "answer_clause_coverage")
    answer_subquestion = _metric_float(score_item, "answer_subquestion_coverage")
    supported = _metric_float(score_item, "answer_supported_clause_rate")
    if not answer:
        return "无答案"
    if answer_clause >= 0.95 and answer_subquestion >= 0.95 and supported >= 0.95:
        return "准确"
    if answer_clause >= 0.5 or answer_subquestion >= 0.5:
        return "部分准确"
    return "证据不足"


def _run_items_by_system_case(runs: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for run in runs:
        system = _text(run.get("system"))
        items = run.get("items") if isinstance(run.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            case_id = _text(item.get("case_id") or item.get("id"))
            if system and case_id:
                out[(system, case_id)] = item
    return out


def _evidence_terms_for_audit(case: dict[str, Any]) -> list[dict[str, Any]]:
    clauses = case.get("evidence_clauses") if isinstance(case.get("evidence_clauses"), list) else []
    rows: list[dict[str, Any]] = []
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        rows.append(
            {
                "id": _text(clause.get("id")),
                "required_terms": clause.get("required_terms") if isinstance(clause.get("required_terms"), list) else [],
            }
        )
    return rows


def _expected_answer_basis(case: dict[str, Any]) -> str:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    key_points = expected.get("answer_key_points") if isinstance(expected.get("answer_key_points"), list) else []
    if key_points:
        return "；".join(_text(point) for point in key_points if _text(point))

    parts: list[str] = []
    for clause in _evidence_terms_for_audit(case):
        terms = [_text(term) for term in clause.get("required_terms", []) if _text(term)]
        if not terms:
            continue
        label = terms[1].rstrip("：:") if len(terms) >= 2 else _text(clause.get("id"))
        value = terms[-1]
        parts.append(f"{label}：{value}" if label and value else value or label)
    return "；".join(part for part in parts if part)


def _clause_label(clause_id: str) -> str:
    labels = {
        "location": "办理地点",
        "phone": "咨询电话",
        "time": "办理时间",
        "materials": "材料",
        "fee": "收费情况",
        "level": "行使层级",
        "type": "办件类型",
        "condition": "受理条件",
    }
    return labels.get(clause_id, clause_id)


def _native_evidence_preview(case: dict[str, Any]) -> str:
    title = _text(case.get("source_record_title") or _case_title(case))
    parts: list[str] = []
    if title:
        parts.append(f"事项：{title}")
    basis = _expected_answer_basis(case)
    if basis:
        parts.append(f"答案依据：{basis}")
    for clause in _evidence_terms_for_audit(case):
        clause_id = _text(clause.get("id"))
        terms = [_text(term) for term in clause.get("required_terms", []) if _text(term)]
        if terms:
            label = _clause_label(clause_id)
            parts.append(f"{label}：{' / '.join(terms)}" if label else " / ".join(terms))
    return _preview("；".join(parts), limit=800)


def _score_reason(score_item: dict[str, Any], raw_item: dict[str, Any]) -> str:
    verdict = _audit_verdict(score_item, raw_item)
    missing_evidence = score_item.get("missing_evidence_clause_ids") if isinstance(score_item.get("missing_evidence_clause_ids"), list) else []
    missing_subquestions = score_item.get("missing_subquestion_ids") if isinstance(score_item.get("missing_subquestion_ids"), list) else []
    wrong_rate = _metric_float(score_item, "wrong_evidence_rate")
    evidence_coverage = _metric_float(score_item, "evidence_coverage")

    if verdict == "准确":
        return "准确：回答覆盖全部必答证据，检索证据可支撑答案，未发现明显错证据。"
    if verdict == "无答案":
        return "无答案：系统没有返回可评估答案，无法对照原始依据完成核验。"

    reasons: list[str] = []
    if missing_evidence:
        reasons.append(f"缺少原始证据条款 {', '.join(_text(item) for item in missing_evidence if _text(item))}")
    if missing_subquestions:
        reasons.append(f"未覆盖必答子问题 {', '.join(_text(item) for item in missing_subquestions if _text(item))}")
    if evidence_coverage < 1.0:
        reasons.append(f"检索证据覆盖率 {evidence_coverage:.2f}")
    if wrong_rate > 0:
        reasons.append(f"错证据率 {wrong_rate:.2f}")
    if not reasons:
        reasons.append("部分指标未达到准确阈值")
    return f"{verdict}：" + "；".join(reasons) + "。"


def _top_record_preview(raw_item: dict[str, Any]) -> str:
    records = raw_item.get("records") if isinstance(raw_item.get("records"), list) else []
    if not records:
        return ""
    first = records[0] if isinstance(records[0], dict) else {}
    metadata = first.get("metadata") if isinstance(first.get("metadata"), dict) else {}
    title = _text(first.get("title") or metadata.get("document_name"))
    content = _text(first.get("content") or first.get("text"))
    return _preview(f"{title} {content}".strip(), limit=360)


def build_audit_rows(report: dict[str, Any], cases: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    case_by_id = {_case_id(case): case for case in cases if _case_id(case)}
    raw_items = _run_items_by_system_case(runs)
    rows: list[dict[str, Any]] = []
    for score_item in report.get("items") if isinstance(report.get("items"), list) else []:
        if not isinstance(score_item, dict):
            continue
        system = _text(score_item.get("system"))
        case_id = _text(score_item.get("case_id"))
        case = case_by_id.get(case_id) or {}
        raw_item = raw_items.get((system, case_id), {})
        verdict = _audit_verdict(score_item, raw_item)
        rows.append(
            {
                "case_id": case_id,
                "source_case_id": _text(case.get("source_case_id")),
                "case_type": _text(case.get("case_type")) or "unknown",
                "knowledge_id": _text(case.get("knowledge_id")),
                "system": system,
                "verdict": verdict,
                "score_reason": _score_reason(score_item, raw_item),
                "business_score": _business_score(score_item),
                "answer_clause_coverage": score_item.get("answer_clause_coverage"),
                "answer_subquestion_coverage": score_item.get("answer_subquestion_coverage"),
                "evidence_coverage": score_item.get("evidence_coverage"),
                "wrong_evidence_rate": score_item.get("wrong_evidence_rate"),
                "source_file": _text(case.get("source_file")),
                "source_section": _text(case.get("source_section")),
                "source_record_title": _text(case.get("source_record_title")),
                "query": _case_question(case),
                "dimension_fields": case.get("dimension_fields") if isinstance(case.get("dimension_fields"), list) else [],
                "expected_answer_basis": _expected_answer_basis(case),
                "native_evidence_preview": _native_evidence_preview(case),
                "required_evidence_terms": _evidence_terms_for_audit(case),
                "missing_evidence_clause_ids": score_item.get("missing_evidence_clause_ids") or [],
                "missing_subquestion_ids": score_item.get("missing_subquestion_ids") or [],
                "answer_preview": _preview(raw_item.get("answer"), limit=600),
                "top_record_preview": _top_record_preview(raw_item),
            }
        )
    rows.sort(key=lambda row: (_text(row.get("case_id")), _text(row.get("system"))))
    return rows


def build_verdict_summary(audit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in audit_rows:
        grouped.setdefault(_text(row.get("system")) or "unknown", []).append(row)

    labels = ["准确", "部分准确", "证据不足", "无答案"]
    summary: list[dict[str, Any]] = []
    for system, rows in sorted(grouped.items()):
        total = len(rows)
        counts = {label: 0 for label in labels}
        for row in rows:
            verdict = _text(row.get("verdict")) or "证据不足"
            counts[verdict] = counts.get(verdict, 0) + 1
        summary.append(
            {
                "system": system,
                "cases": total,
                "accurate": counts.get("准确", 0),
                "partially_accurate": counts.get("部分准确", 0),
                "insufficient_evidence": counts.get("证据不足", 0),
                "no_answer": counts.get("无答案", 0),
                "accurate_rate": round(counts.get("准确", 0) / total, 6) if total else 0.0,
                "usable_rate": round((counts.get("准确", 0) + counts.get("部分准确", 0)) / total, 6) if total else 0.0,
            }
        )
    return summary


def build_top_issue_cases(audit_rows: list[dict[str, Any]], *, per_system: int = 10) -> list[dict[str, Any]]:
    severity = {"无答案": 4, "证据不足": 3, "部分准确": 2, "准确": 1}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in audit_rows:
        grouped.setdefault(_text(row.get("system")) or "unknown", []).append(row)

    issues: list[dict[str, Any]] = []
    for system, rows in sorted(grouped.items()):
        sorted_rows = sorted(
            rows,
            key=lambda row: (
                severity.get(_text(row.get("verdict")), 3),
                -_metric_float(row, "business_score"),
                _metric_float(row, "wrong_evidence_rate"),
                len(row.get("missing_evidence_clause_ids") if isinstance(row.get("missing_evidence_clause_ids"), list) else []),
            ),
            reverse=True,
        )
        for row in sorted_rows[: max(0, int(per_system))]:
            issues.append(
                {
                    "system": system,
                    "case_id": row.get("case_id"),
                    "case_type": row.get("case_type"),
                    "verdict": row.get("verdict"),
                    "business_score": row.get("business_score"),
                    "wrong_evidence_rate": row.get("wrong_evidence_rate"),
                    "source_record_title": row.get("source_record_title"),
                    "query": row.get("query"),
                    "expected_answer_basis": row.get("expected_answer_basis"),
                    "missing_evidence_clause_ids": row.get("missing_evidence_clause_ids") or [],
                    "missing_subquestion_ids": row.get("missing_subquestion_ids") or [],
                    "answer_preview": row.get("answer_preview"),
                }
            )
    return issues


def build_case_type_advantage(report: dict[str, Any], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    case_types = {_case_id(case): _text(case.get("case_type")) or "unknown" for case in cases}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in report.get("items") if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        case_type = case_types.get(_text(item.get("case_id")), "unknown")
        system = _text(item.get("system")) or "unknown"
        grouped.setdefault((case_type, system), []).append(item)

    rows: list[dict[str, Any]] = []
    for (case_type, system), items in sorted(grouped.items()):
        cases_count = len(items)
        if cases_count <= 0:
            continue
        scores = [_business_score(item) for item in items]
        rows.append(
            {
                "case_type": case_type,
                "system": system,
                "cases": cases_count,
                "business_score": round(sum(scores) / cases_count, 6),
                "answer_clause_coverage": round(
                    sum(_metric_float(item, "answer_clause_coverage") for item in items) / cases_count,
                    6,
                ),
                "answer_subquestion_coverage": round(
                    sum(_metric_float(item, "answer_subquestion_coverage") for item in items) / cases_count,
                    6,
                ),
                "evidence_coverage": round(
                    sum(_metric_float(item, "evidence_coverage") for item in items) / cases_count,
                    6,
                ),
                "wrong_evidence_rate": round(
                    sum(_metric_float(item, "wrong_evidence_rate") for item in items) / cases_count,
                    6,
                ),
            }
        )
    return rows


def _dimensions_for_case(case: dict[str, Any]) -> list[str]:
    subquestions = case.get("subquestions") if isinstance(case.get("subquestions"), list) else []
    dimensions: list[str] = []
    for item in subquestions:
        value = _text(item.get("id") if isinstance(item, dict) else item)
        if value:
            dimensions.append(value)
    if not dimensions:
        fields = case.get("dimension_fields") if isinstance(case.get("dimension_fields"), list) else []
        dimensions = [_text(item) for item in fields if _text(item)]
    return list(dict.fromkeys(dimensions))


def build_dimension_advantage(report: dict[str, Any], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dimensions_by_case = {_case_id(case): _dimensions_for_case(case) for case in cases if _case_id(case)}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in report.get("items") if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        system = _text(item.get("system")) or "unknown"
        for dimension in dimensions_by_case.get(_text(item.get("case_id")), []) or ["unknown"]:
            grouped.setdefault((dimension, system), []).append(item)

    rows: list[dict[str, Any]] = []
    for (dimension, system), items in sorted(grouped.items()):
        cases_count = len(items)
        if cases_count <= 0:
            continue
        scores = [_business_score(item) for item in items]
        rows.append(
            {
                "dimension": dimension,
                "system": system,
                "cases": cases_count,
                "business_score": round(sum(scores) / cases_count, 6),
                "answer_clause_coverage": round(
                    sum(_metric_float(item, "answer_clause_coverage") for item in items) / cases_count,
                    6,
                ),
                "answer_subquestion_coverage": round(
                    sum(_metric_float(item, "answer_subquestion_coverage") for item in items) / cases_count,
                    6,
                ),
                "evidence_coverage": round(
                    sum(_metric_float(item, "evidence_coverage") for item in items) / cases_count,
                    6,
                ),
                "wrong_evidence_rate": round(
                    sum(_metric_float(item, "wrong_evidence_rate") for item in items) / cases_count,
                    6,
                ),
            }
        )
    return rows


def _winner_by_field(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_text(row.get(field)) or "unknown", []).append(row)
    winners: list[dict[str, Any]] = []
    for value, items in sorted(grouped.items()):
        winner = max(
            items,
            key=lambda item: (
                _metric_float(item, "business_score"),
                _metric_float(item, "answer_clause_coverage"),
                -_metric_float(item, "wrong_evidence_rate"),
            ),
        )
        winners.append(winner | {field: value})
    return winners


def _winner_by_case_type(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _winner_by_field(rows, "case_type")


def _winner_by_dimension(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _winner_by_field(rows, "dimension")


def _increment_system(summary: dict[str, Any], system: str, key: str, label: str) -> None:
    if not system:
        return
    row = summary.setdefault(system, {"case_type_wins": 0, "dimension_wins": 0, "winning_case_types": [], "winning_dimensions": []})
    row[key] = int(row.get(key) or 0) + 1
    list_key = "winning_case_types" if key == "case_type_wins" else "winning_dimensions"
    if label:
        row.setdefault(list_key, []).append(label)


def build_advantage_summary(report: dict[str, Any]) -> dict[str, Any]:
    leaderboard = report.get("leaderboard") if isinstance(report.get("leaderboard"), list) else []
    case_type_rows = report.get("case_type_advantage") if isinstance(report.get("case_type_advantage"), list) else []
    dimension_rows = report.get("dimension_advantage") if isinstance(report.get("dimension_advantage"), list) else []

    system_summary: dict[str, Any] = {}
    for row in _winner_by_case_type([item for item in case_type_rows if isinstance(item, dict)]):
        _increment_system(system_summary, _text(row.get("system")), "case_type_wins", _text(row.get("case_type")))
    for row in _winner_by_dimension([item for item in dimension_rows if isinstance(item, dict)]):
        _increment_system(system_summary, _text(row.get("system")), "dimension_wins", _text(row.get("dimension")))

    best_system = ""
    if leaderboard and isinstance(leaderboard[0], dict):
        best_system = _text(leaderboard[0].get("system"))

    strongest = sorted(
        (
            {"system": system, **values, "total_wins": int(values.get("case_type_wins") or 0) + int(values.get("dimension_wins") or 0)}
            for system, values in system_summary.items()
        ),
        key=lambda item: (int(item.get("total_wins") or 0), int(item.get("dimension_wins") or 0), _text(item.get("system"))),
        reverse=True,
    )
    return {
        "overall_best_system": best_system,
        "systems": dict(sorted(system_summary.items())),
        "strongest_by_win_count": strongest,
        "case_type_winner_count": len(_winner_by_case_type([item for item in case_type_rows if isinstance(item, dict)])),
        "dimension_winner_count": len(_winner_by_dimension([item for item in dimension_rows if isinstance(item, dict)])),
    }


def build_completion_status(
    *,
    runs: list[dict[str, Any]],
    apps: list[AppSpec],
    requested_cases: int,
    executed_cases: int,
    expected_cases: int = DEFAULT_TARGET_COUNT,
    include_mimirq_direct: bool = False,
) -> dict[str, Any]:
    required_systems = {app.label for app in apps}
    if include_mimirq_direct:
        required_systems.add("mimirq_direct")
    run_by_system = {_text(run.get("system")): run for run in runs if _text(run.get("system"))}
    missing_systems = sorted(required_systems - set(run_by_system))
    skipped_systems: list[str] = []
    incomplete_systems: list[str] = []
    failed_systems: list[str] = []
    system_rows: list[dict[str, Any]] = []
    for system in sorted(required_systems):
        run = run_by_system.get(system) or {}
        summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
        items = run.get("items") if isinstance(run.get("items"), list) else []
        skipped = summary.get("skipped") is True
        cases = int(summary.get("cases") or 0)
        succeeded = int(summary.get("succeeded") or 0)
        failed = int(summary.get("failed") or 0)
        if skipped:
            skipped_systems.append(system)
        if cases != executed_cases or len(items) != executed_cases:
            incomplete_systems.append(system)
        if (not skipped) and failed > 0:
            failed_systems.append(system)
        system_rows.append(
            {
                "system": system,
                "cases": cases,
                "items": len(items),
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
                "complete": (not skipped) and cases == executed_cases and len(items) == executed_cases,
            }
        )
    target_case_count_ok = requested_cases >= expected_cases and executed_cases == expected_cases
    all_systems_present = not missing_systems
    all_systems_executed = not skipped_systems and not incomplete_systems
    completion_key = f"complete_{len(required_systems)}way_{expected_cases}"
    return {
        "expected_cases": expected_cases,
        "requested_cases": requested_cases,
        "executed_cases": executed_cases,
        "expected_systems": len(required_systems),
        "required_systems": sorted(required_systems),
        "target_case_count_ok": target_case_count_ok,
        "all_systems_present": all_systems_present,
        "all_systems_executed": all_systems_executed,
        "all_systems_succeeded": not failed_systems,
        "completion_key": completion_key,
        "complete": target_case_count_ok and all_systems_present and all_systems_executed,
        "complete_3way_800": target_case_count_ok and all_systems_present and all_systems_executed,
        "missing_systems": missing_systems,
        "skipped_systems": skipped_systems,
        "incomplete_systems": sorted(set(incomplete_systems)),
        "failed_systems": sorted(set(failed_systems)),
        "systems": system_rows,
    }


def build_comparison_markdown(report: dict[str, Any], *, apps: list[AppSpec], cases: list[dict[str, Any]]) -> str:
    skipped_systems = (report.get("summary") or {}).get("skipped_systems") or []
    completion = report.get("completion_status") if isinstance(report.get("completion_status"), dict) else {}
    verdict_summary = report.get("audit_verdict_summary") if isinstance(report.get("audit_verdict_summary"), list) else []
    top_issue_cases = report.get("top_issue_cases") if isinstance(report.get("top_issue_cases"), list) else []
    leaderboard = report.get("leaderboard") if isinstance(report.get("leaderboard"), list) else []
    case_type_rows = build_case_type_advantage(report, cases)
    case_type_winners = _winner_by_case_type(case_type_rows)
    dimension_rows = report.get("dimension_advantage") if isinstance(report.get("dimension_advantage"), list) else build_dimension_advantage(report, cases)
    dimension_winners = _winner_by_dimension([row for row in dimension_rows if isinstance(row, dict)])
    advantage_summary = report.get("advantage_summary") if isinstance(report.get("advantage_summary"), dict) else build_advantage_summary(report | {"dimension_advantage": dimension_rows})
    best_system = leaderboard[0] if leaderboard and isinstance(leaderboard[0], dict) else None
    lines = [
        "# Dify 3-Way Benchmark",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Cases: `{(report.get('summary') or {}).get('cases')}`",
        "- Judge: deterministic evidence-clause matching, no LLM judge.",
        "",
        "## 中文结论摘要",
        "",
    ]
    if completion:
        lines.append(
            f"- 完整性：`complete_3way_800={str(completion.get('complete_3way_800')).lower()}`；已执行 `{completion.get('executed_cases')}` / 目标 `{completion.get('expected_cases')}` 题。"
        )
    if skipped_systems:
        lines.append(
            f"- 当前报告尚不能代表完整三路结论；以下系统因缺少 App API key 被跳过：`{', '.join(skipped_systems)}`。"
        )
    if best_system:
        lines.append(
            f"- 当前已执行系统中综合排名第一：`{best_system.get('system')}`，业务综合分 `{_business_score_system(best_system):.3f}`。"
        )
    else:
        lines.append("- 当前还没有可评分系统；先完成 `--preflight` 和远程 run 后再看优势结论。")
    lines.append("- 业务综合分权重：回答证据覆盖 35%、回答子问题覆盖 25%、检索证据覆盖 20%、回答有证据支撑 15%、少错证据 5%。")
    lines.extend([
        "",
        "## Apps",
        "",
        "| Label | App ID | Type | Description |",
        "| --- | --- | --- | --- |",
    ])
    for app in apps:
        lines.append(f"| {app.label} | `{app.app_id}` | {app.kind} | {app.description} |")
    strongest = advantage_summary.get("strongest_by_win_count") if isinstance(advantage_summary.get("strongest_by_win_count"), list) else []
    if advantage_summary or strongest:
        lines.extend(
            [
                "",
                "## 优势汇总",
                "",
                f"- 总体排名第一：`{advantage_summary.get('overall_best_system') or '-'}`。",
                f"- 已统计问题类型胜出项：`{advantage_summary.get('case_type_winner_count', 0)}`；业务维度胜出项：`{advantage_summary.get('dimension_winner_count', 0)}`。",
            ]
        )
        if strongest:
            lines.extend(["", "| 系统 | 总胜出项 | 问题类型胜出 | 业务维度胜出 |", "| --- | ---: | ---: | ---: |"])
            for row in strongest:
                lines.append(
                    "| `{system}` | {total} | {case_types} | {dimensions} |".format(
                        system=row.get("system"),
                        total=int(row.get("total_wins") or 0),
                        case_types=int(row.get("case_type_wins") or 0),
                        dimensions=int(row.get("dimension_wins") or 0),
                    )
                )
    if verdict_summary:
        lines.extend(
            [
                "",
                "## 审计判定分布",
                "",
                "| 系统 | 题数 | 准确 | 部分准确 | 证据不足 | 无答案 | 准确率 | 可用率 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in verdict_summary:
            lines.append(
                "| `{system}` | {cases} | {accurate} | {partially} | {insufficient} | {no_answer} | {accurate_rate:.3f} | {usable_rate:.3f} |".format(
                    system=row.get("system"),
                    cases=int(row.get("cases") or 0),
                    accurate=int(row.get("accurate") or 0),
                    partially=int(row.get("partially_accurate") or 0),
                    insufficient=int(row.get("insufficient_evidence") or 0),
                    no_answer=int(row.get("no_answer") or 0),
                    accurate_rate=_metric_float(row, "accurate_rate"),
                    usable_rate=_metric_float(row, "usable_rate"),
                )
            )
    if case_type_winners:
        lines.extend(
            [
                "",
                "## 按问题类型看优势",
                "",
                "| 问题类型 | 当前胜出系统 | 题数 | 业务综合分 | 回答证据覆盖 | 回答子问题覆盖 | 错证据率 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in case_type_winners:
            lines.append(
                "| {case_type} | `{system}` | {cases} | {score:.3f} | {answer_clause:.3f} | {answer_subq:.3f} | {wrong:.3f} |".format(
                    case_type=row.get("case_type"),
                    system=row.get("system"),
                    cases=int(row.get("cases") or 0),
                    score=_metric_float(row, "business_score"),
                    answer_clause=_metric_float(row, "answer_clause_coverage"),
                    answer_subq=_metric_float(row, "answer_subquestion_coverage"),
                    wrong=_metric_float(row, "wrong_evidence_rate"),
                )
            )
    if dimension_winners:
        lines.extend(
            [
                "",
                "## 按业务维度看优势",
                "",
                "| 业务维度 | 当前胜出系统 | 题数 | 业务综合分 | 回答证据覆盖 | 回答子问题覆盖 | 错证据率 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in dimension_winners:
            lines.append(
                "| {dimension} | `{system}` | {cases} | {score:.3f} | {answer_clause:.3f} | {answer_subq:.3f} | {wrong:.3f} |".format(
                    dimension=row.get("dimension"),
                    system=row.get("system"),
                    cases=int(row.get("cases") or 0),
                    score=_metric_float(row, "business_score"),
                    answer_clause=_metric_float(row, "answer_clause_coverage"),
                    answer_subq=_metric_float(row, "answer_subquestion_coverage"),
                    wrong=_metric_float(row, "wrong_evidence_rate"),
                )
            )
    if top_issue_cases:
        lines.extend(
            [
                "",
                "## Top 问题样本",
                "",
                "| 系统 | 判定 | 分数 | 问题类型 | 事项 | 问题 | 缺失证据 |",
                "| --- | --- | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in top_issue_cases[:30]:
            lines.append(
                "| `{system}` | {verdict} | {score:.3f} | {case_type} | {title} | {query} | {missing} |".format(
                    system=row.get("system"),
                    verdict=row.get("verdict"),
                    score=_metric_float(row, "business_score"),
                    case_type=row.get("case_type"),
                    title=_preview(row.get("source_record_title"), limit=42),
                    query=_preview(row.get("query"), limit=72),
                    missing=_preview(row.get("missing_evidence_clause_ids"), limit=60),
                )
            )
    lines.extend(["", "## Leaderboard", ""])
    lines.append(build_markdown_report(report).split("## Leaderboard", 1)[1].split("## Missing Evidence", 1)[0].strip())
    lines.extend(["", "## Notes", ""])
    lines.append("- Secrets are not written to benchmark artifacts.")
    if skipped_systems:
        lines.append(f"- Skipped systems because API keys were missing: `{', '.join(skipped_systems)}`.")
    lines.append("- Missing API keys produce skipped run files; provide `--app-key-file` or explicit `--app` values to execute remote Dify calls.")
    return "\n".join(lines).rstrip() + "\n"


def build_sharing_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    completion = report.get("completion_status") if isinstance(report.get("completion_status"), dict) else {}
    leaderboard = report.get("leaderboard") if isinstance(report.get("leaderboard"), list) else []
    verdict_summary = report.get("audit_verdict_summary") if isinstance(report.get("audit_verdict_summary"), list) else []
    case_type_advantage = report.get("case_type_advantage") if isinstance(report.get("case_type_advantage"), list) else []
    dimension_advantage = report.get("dimension_advantage") if isinstance(report.get("dimension_advantage"), list) else []
    advantage_summary = report.get("advantage_summary") if isinstance(report.get("advantage_summary"), dict) else build_advantage_summary(report)
    top_issue_cases = report.get("top_issue_cases") if isinstance(report.get("top_issue_cases"), list) else []
    audit_review = report.get("audit_review") if isinstance(report.get("audit_review"), dict) else {}
    skipped_systems = summary.get("skipped_systems") if isinstance(summary.get("skipped_systems"), list) else []
    expected_systems = int(completion.get("expected_systems") or len(leaderboard) or 0)
    expected_cases = int(completion.get("expected_cases") or DEFAULT_TARGET_COUNT)
    completion_key = _text(completion.get("completion_key")) or f"complete_{expected_systems}way_{expected_cases}"
    title = f"Dify {expected_systems}路评测摘要" if expected_systems > 0 else "Dify 评测摘要"

    lines = [
        f"# {title}",
        "",
        f"- 生成时间：`{report.get('generated_at')}`",
        f"- 执行题数：`{summary.get('executed_cases', summary.get('cases'))}` / 目标 `{expected_cases}`",
        f"- 完整性：`{completion_key}={str(completion.get('complete')).lower()}`",
    ]
    if skipped_systems:
        lines.append(f"- 未纳入完整结论的系统：`{', '.join(_text(item) for item in skipped_systems)}`")
    strongest = advantage_summary.get("strongest_by_win_count") if isinstance(advantage_summary.get("strongest_by_win_count"), list) else []
    if advantage_summary:
        lines.extend(["", "## 优势汇总", ""])
        lines.append(f"- 总体排名第一：`{advantage_summary.get('overall_best_system') or '-'}`")
        if strongest:
            top = strongest[0]
            lines.append(
                "- 类型/维度胜出最多：`{system}`，总胜出 `{total}` 项（问题类型 `{case_types}`，业务维度 `{dimensions}`）。".format(
                    system=top.get("system"),
                    total=int(top.get("total_wins") or 0),
                    case_types=int(top.get("case_type_wins") or 0),
                    dimensions=int(top.get("dimension_wins") or 0),
                )
            )
    lines.extend(["", "## 排行榜", "", "| 排名 | 系统 | 题数 | 回答证据覆盖 | 回答子问题覆盖 | 错证据率 | 延迟 ms |", "| ---: | --- | ---: | ---: | ---: | ---: | ---: |"])
    for row in leaderboard:
        if not isinstance(row, dict):
            continue
        latency = row.get("mean_latency_ms")
        lines.append(
            "| {rank} | `{system}` | {cases} | {answer_clause:.3f} | {answer_subq:.3f} | {wrong:.3f} | {latency} |".format(
                rank=int(row.get("rank") or 0),
                system=row.get("system"),
                cases=int(row.get("cases") or 0),
                answer_clause=_metric_float(row, "mean_answer_clause_coverage"),
                answer_subq=_metric_float(row, "mean_answer_subquestion_coverage"),
                wrong=_metric_float(row, "mean_wrong_evidence_rate"),
                latency="-" if latency is None else f"{float(latency):.1f}",
            )
        )
    if verdict_summary:
        lines.extend(["", "## 准确率结构", "", "| 系统 | 准确 | 部分准确 | 证据不足 | 无答案 | 准确率 | 可用率 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
        for row in verdict_summary:
            if not isinstance(row, dict):
                continue
            lines.append(
                "| `{system}` | {accurate} | {partial} | {insufficient} | {no_answer} | {accurate_rate:.3f} | {usable_rate:.3f} |".format(
                    system=row.get("system"),
                    accurate=int(row.get("accurate") or 0),
                    partial=int(row.get("partially_accurate") or 0),
                    insufficient=int(row.get("insufficient_evidence") or 0),
                    no_answer=int(row.get("no_answer") or 0),
                    accurate_rate=_metric_float(row, "accurate_rate"),
                    usable_rate=_metric_float(row, "usable_rate"),
                )
            )
    if case_type_advantage:
        winners = _winner_by_case_type([row for row in case_type_advantage if isinstance(row, dict)])
        lines.extend(["", "## 类型优势", "", "| 问题类型 | 当前胜出系统 | 业务综合分 |", "| --- | --- | ---: |"])
        for row in winners:
            lines.append(
                "| {case_type} | `{system}` | {score:.3f} |".format(
                    case_type=row.get("case_type"),
                    system=row.get("system"),
                    score=_metric_float(row, "business_score"),
                )
            )
    if dimension_advantage:
        winners = _winner_by_dimension([row for row in dimension_advantage if isinstance(row, dict)])
        lines.extend(["", "## 业务维度优势", "", "| 业务维度 | 当前胜出系统 | 业务综合分 |", "| --- | --- | ---: |"])
        for row in winners:
            lines.append(
                "| {dimension} | `{system}` | {score:.3f} |".format(
                    dimension=row.get("dimension"),
                    system=row.get("system"),
                    score=_metric_float(row, "business_score"),
                )
            )
    if top_issue_cases:
        lines.extend(["", "## 优先排查样本", "", "| 系统 | 判定 | 分数 | 事项 | 问题 |", "| --- | --- | ---: | --- | --- |"])
        for row in top_issue_cases[:10]:
            if not isinstance(row, dict):
                continue
            lines.append(
                "| `{system}` | {verdict} | {score:.3f} | {title} | {query} |".format(
                    system=row.get("system"),
                    verdict=row.get("verdict"),
                    score=_metric_float(row, "business_score"),
                    title=_preview(row.get("source_record_title"), limit=42),
                    query=_preview(row.get("query"), limit=72),
                )
            )
    lines.extend(
        [
            "",
            "## 附件",
            "",
            "- 详细报告：`comparison_report.md`",
            "- 机器可读报告：`comparison_report.json`",
            f"- 逐题审计 JSONL：`{audit_review.get('jsonl_path', 'audit_review.jsonl')}`",
            f"- 逐题审计 CSV：`{audit_review.get('csv_path', 'audit_review.csv')}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and run an evidence-first Dify/MimirQ benchmark.")
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--golden-cases", default=DEFAULT_GOLDEN_CASES)
    parser.add_argument("--prebuilt-cases", default="", help="Use a prebuilt benchmark cases JSON (list or {cases:[...]}) and skip internal 800-case expansion.")
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--seed", type=int, default=20260704)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--app-key-file", default="")
    parser.add_argument(
        "--app",
        action="append",
        default=[],
        help="label:app_id:kind:api_key_or_key_name[:mode]. Repeat for each app.",
    )
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Run only first N generated cases; 0 means all.")
    parser.add_argument("--sample-per-type", type=int, default=0, help="Run N cases per generated case_type; overrides --limit when > 0.")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--response-mode", choices=["blocking", "streaming"], default="blocking")
    parser.add_argument("--workflow-query-key", default="query")
    parser.add_argument("--user-prefix", default="mimirq-dify-3way")
    parser.add_argument("--include-mimirq-direct", action="store_true")
    parser.add_argument("--mimirq-base-url", default=DEFAULT_MIMIRQ_BASE_URL)
    parser.add_argument("--mimirq-token", default="")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--resume", action="store_true", help="Reuse existing run_*.json items in --out-dir and only call missing cases.")
    parser.add_argument("--retry-failures", action="store_true", help="With --resume, re-run existing failed cases instead of reusing them.")
    parser.add_argument("--flush-every", type=int, default=50, help="Write partial run_*.json checkpoints every N completed cases; 0 disables incremental flush.")
    parser.add_argument("--preflight", action="store_true", help="Probe each Dify app with one generated case, without running the full benchmark.")
    parser.add_argument("--report-only", action="store_true", help="Only read existing run_*.json files and regenerate comparison/audit reports; no API calls or run-file rewrites.")
    parser.add_argument("--strict-complete", action="store_true", help="Exit non-zero unless all three Dify apps ran the full 800-case benchmark.")
    parser.add_argument("--write-bundle", action="store_true", help="Write a zip bundle with reports, audit files, manifests, and run files.")
    parser.add_argument("--auto-mode", action="store_true", help="Probe chat/workflow endpoints first and use the working Dify App mode.")
    parser.add_argument(
        "--no-http-history-backfill",
        action="store_true",
        help="Do not backfill HTTP_mimirq evidence from locally ingested MimirQ history citations.",
    )
    parser.add_argument(
        "--http-history-backfill-wait-sec",
        type=float,
        default=3.0,
        help="Max seconds to wait for async MimirQ history ingest after each HTTP_mimirq Dify response.",
    )
    parser.add_argument(
        "--http-history-backfill-poll-sec",
        type=float,
        default=0.5,
        help="Polling interval for HTTP_mimirq history evidence backfill.",
    )
    parser.add_argument(
        "--no-dify-console-backfill",
        action="store_true",
        help="Do not use Dify Console node executions to backfill HTTP_mimirq evidence.",
    )
    parser.add_argument(
        "--dify-console-base-url",
        default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or "https://dify.example.com:5001/console/api",
    )
    parser.add_argument("--dify-console-token", default=os.getenv("DIFY_CONSOLE_TOKEN") or "")
    parser.add_argument("--dify-console-storage-state", default="/tmp/dify_console_storage_state.json")
    parser.add_argument("--generate-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    apps = load_app_specs(list(args.app or []), str(args.app_key_file))
    if _text(args.prebuilt_cases):
        cases = load_prebuilt_cases(str(args.prebuilt_cases))
    else:
        cases = build_benchmark_cases(
            mixed_cases=load_cases(str(args.cases)),
            golden_cases=load_cases(str(args.golden_cases)),
            target_count=int(args.target_count),
            seed=int(args.seed),
        )
    cases_to_run = select_cases_to_run(
        cases,
        limit=int(args.limit or 0),
        sample_per_type=int(args.sample_per_type or 0),
    )
    expected_case_count = resolve_expected_case_count(
        prebuilt_cases=str(args.prebuilt_cases),
        target_count=int(args.target_count),
        cases=cases,
    )
    _write_json(out_dir / "key_requirements.json", build_key_requirements(apps))
    _write_json(
        out_dir / "cases_800.json",
        {"schema": "mimirq.dify_3way_benchmark.cases.v1", "summary": summarize_cases(cases), "cases": cases},
    )
    _write_json(
        out_dir / "truth_manifest.json",
        {
            "schema": "mimirq.dify_3way_benchmark.truth_manifest.v1",
            "summary": summarize_cases(cases),
            "items": build_truth_manifest(cases),
        },
    )
    if args.generate_only:
        _write_json(out_dir / "apps.json", {"schema": "mimirq.dify_3way_benchmark.apps.v1", "apps": [app.__dict__ | {"api_key": "<redacted>"} for app in apps]})
        print(json.dumps({"cases": len(cases), "cases_path": str(out_dir / "cases_800.json"), "apps": len(apps)}, ensure_ascii=False))
        return 0

    console_token = ""
    if not bool(args.no_dify_console_backfill):
        try:
            from scripts.changzhou_gov_dify_trace_report import load_console_token

            console_token = load_console_token(
                str(args.dify_console_token),
                str(args.dify_console_storage_state),
            )
        except Exception:
            console_token = ""

    if not args.report_only and (args.auto_mode or any(app.mode == "auto" for app in apps)):
        apps, mode_report = resolve_app_modes(
            apps=apps,
            probe_case=cases_to_run[0] if cases_to_run else {},
            base_url=str(args.base_url),
            timeout=float(args.timeout),
            response_mode=_fixed_response_mode(str(args.response_mode)),
            workflow_query_key=str(args.workflow_query_key),
            user_prefix=str(args.user_prefix),
            force=bool(args.auto_mode),
        )
        _write_json(out_dir / "mode_resolution_report.json", mode_report)
    _write_json(out_dir / "apps.json", {"schema": "mimirq.dify_3way_benchmark.apps.v1", "apps": [app.__dict__ | {"api_key": "<redacted>"} for app in apps]})

    if args.preflight:
        report = run_preflight(
            apps=apps,
            cases=cases_to_run,
            base_url=str(args.base_url),
            timeout=float(args.timeout),
            response_mode=_fixed_response_mode(str(args.response_mode)),
            workflow_query_key=str(args.workflow_query_key),
            user_prefix=str(args.user_prefix),
            http_history_backfill=not bool(args.no_http_history_backfill),
            history_backfill_wait_sec=float(args.http_history_backfill_wait_sec),
            history_backfill_poll_sec=float(args.http_history_backfill_poll_sec),
            console_base_url=str(args.dify_console_base_url),
            console_token=console_token,
            console_backfill=not bool(args.no_dify_console_backfill),
        )
        _write_json(out_dir / "preflight_report.json", report)
        print(
            json.dumps(
                {
                    "out_dir": str(out_dir),
                    "preflight": (report.get("summary") or {}),
                },
                ensure_ascii=False,
            )
        )
        return 0

    runs: list[dict[str, Any]] = []
    if args.report_only:
        runs = load_report_only_runs(out_dir=out_dir, apps=apps, include_mimirq_direct=bool(args.include_mimirq_direct))
    elif args.include_mimirq_direct:
        direct_run_path = out_dir / "run_mimirq_direct.json"
        run = run_mimirq_direct(
            cases=cases_to_run,
            base_url=str(args.mimirq_base_url),
            token=load_mimirq_token(str(args.mimirq_token), env_file=str(args.env_file)),
            timeout=float(args.timeout),
            concurrency=int(args.concurrency),
            existing_items=_load_existing_run_items(direct_run_path) if args.resume else None,
            retry_failures=bool(args.retry_failures),
            run_path=direct_run_path,
            flush_every=int(args.flush_every),
        )
        runs.append(run)
        _write_json(direct_run_path, run)

    if not args.report_only:
        for app in apps:
            run_path = out_dir / f"run_{app.label}.json"
            run = run_app(
                app=app,
                cases=cases_to_run,
                base_url=str(args.base_url),
                timeout=float(args.timeout),
                response_mode=_fixed_response_mode(str(args.response_mode)),
                concurrency=int(args.concurrency),
                workflow_query_key=str(args.workflow_query_key),
                user_prefix=str(args.user_prefix),
                existing_items=_load_existing_run_items(run_path) if args.resume else None,
                retry_failures=bool(args.retry_failures),
                run_path=run_path,
                flush_every=int(args.flush_every),
                http_history_backfill=not bool(args.no_http_history_backfill),
                history_backfill_wait_sec=float(args.http_history_backfill_wait_sec),
                history_backfill_poll_sec=float(args.http_history_backfill_poll_sec),
                console_base_url=str(args.dify_console_base_url),
                console_token=console_token,
                console_backfill=not bool(args.no_dify_console_backfill),
            )
            runs.append(run)
            _write_json(run_path, run)

    skipped_systems = [
        _text(run.get("system"))
        for run in runs
        if isinstance(run.get("summary"), dict) and run["summary"].get("skipped") is True
    ]
    executed_runs = [
        run
        for run in runs
        if not (isinstance(run.get("summary"), dict) and run["summary"].get("skipped") is True)
    ]
    report = evaluate_mixed_rag_quality(cases=cases_to_run, runs=executed_runs) if executed_runs else {
        "schema": "mimirq.mixed_rag_quality_report.v1",
        "generated_at": _utc_now_text(),
        "method": {"judge": "deterministic_term_and_metadata_matching", "llm_judge": False},
        "summary": {"cases": len(cases_to_run), "systems": 0, "items": 0},
        "systems": [],
        "leaderboard": [],
        "pairwise": [],
        "items": [],
    }
    report["apps"] = [app.__dict__ | {"api_key": "<redacted>"} for app in apps]
    report["summary"]["requested_cases"] = len(cases)
    report["summary"]["executed_cases"] = len(cases_to_run)
    report["summary"]["base_url"] = str(args.base_url).rstrip("/")
    report["summary"]["skipped_systems"] = skipped_systems
    report["summary"]["case_distribution"] = summarize_cases(cases_to_run)
    completion_status = build_completion_status(
        runs=runs,
        apps=apps,
        requested_cases=len(cases),
        executed_cases=len(cases_to_run),
        expected_cases=expected_case_count,
        include_mimirq_direct=bool(args.include_mimirq_direct),
    )
    report["completion_status"] = completion_status
    report["business_score_weights"] = {
        "answer_clause_coverage": 0.35,
        "answer_subquestion_coverage": 0.25,
        "evidence_coverage": 0.2,
        "answer_supported_clause_rate": 0.15,
        "inverse_wrong_evidence_rate": 0.05,
    }
    report["case_type_advantage"] = build_case_type_advantage(report, cases_to_run)
    report["dimension_advantage"] = build_dimension_advantage(report, cases_to_run)
    report["advantage_summary"] = build_advantage_summary(report)
    audit_rows = build_audit_rows(report, cases_to_run, runs)
    report["audit_review"] = {
        "rows": len(audit_rows),
        "jsonl_path": str(out_dir / "audit_review.jsonl"),
        "csv_path": str(out_dir / "audit_review.csv"),
    }
    report["sharing_summary_path"] = str(out_dir / "summary_for_sharing.md")
    report["artifact_manifest_path"] = str(out_dir / "artifact_manifest.json")
    report["audit_verdict_summary"] = build_verdict_summary(audit_rows)
    report["top_issue_cases"] = build_top_issue_cases(audit_rows, per_system=10)
    _write_json(out_dir / "comparison_report.json", report)
    _write_jsonl(out_dir / "audit_review.jsonl", audit_rows)
    _write_csv(
        out_dir / "audit_review.csv",
        audit_rows,
        fieldnames=[
            "case_id",
            "case_type",
            "system",
            "verdict",
            "score_reason",
            "business_score",
            "answer_clause_coverage",
            "answer_subquestion_coverage",
            "evidence_coverage",
            "wrong_evidence_rate",
            "source_record_title",
            "source_file",
            "query",
            "expected_answer_basis",
            "native_evidence_preview",
            "missing_evidence_clause_ids",
            "missing_subquestion_ids",
            "required_evidence_terms",
            "answer_preview",
            "top_record_preview",
        ],
    )
    (out_dir / "comparison_report.md").write_text(
        build_comparison_markdown(report, apps=apps, cases=cases_to_run),
        encoding="utf-8",
    )
    (out_dir / "summary_for_sharing.md").write_text(build_sharing_markdown(report), encoding="utf-8")
    _write_json(out_dir / "comparison_report.json", report)
    artifact_manifest = build_artifact_manifest(
        out_dir=out_dir,
        report=report,
        apps=apps,
        include_mimirq_direct=bool(args.include_mimirq_direct),
    )
    _write_json(out_dir / "artifact_manifest.json", artifact_manifest)
    bundle_path = write_artifact_bundle(out_dir=out_dir, manifest=artifact_manifest) if args.write_bundle else None
    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "cases": len(cases_to_run),
                "systems": int((report.get("summary") or {}).get("systems") or 0),
                "skipped_systems": skipped_systems,
                "complete_3way_800": completion_status.get("complete_3way_800"),
                "bundle_path": str(bundle_path) if bundle_path else None,
            },
            ensure_ascii=False,
        )
    )
    if args.strict_complete and completion_status.get("complete_3way_800") is not True:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
