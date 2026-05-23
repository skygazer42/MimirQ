#!/usr/bin/env python3
"""Verify knowledge-base inventory and dataset boundary behavior against a live API.

This script intentionally uses only the Python standard library so it can run
on production-like hosts without extra dependencies.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


@dataclass
class ApiResponse:
    status: int
    body: Any
    elapsed_sec: float


class LiveApi:
    def __init__(self, base_url: str, tenant_id: str, account_id: str, user_id: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.headers = {
            "X-Tenant-ID": tenant_id,
            "X-Account-ID": account_id,
            "X-User-ID": user_id,
        }

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> ApiResponse:
        headers = dict(self.headers)
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request(method, path, data=data, headers=headers, timeout=int(timeout or self.timeout))

    def multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        timeout: int | None = None,
    ) -> ApiResponse:
        boundary = f"----MimirQKbBoundary{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            chunks.append(str(value).encode("utf-8"))
            chunks.append(b"\r\n")
        mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{file_path.name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode()
        )
        chunks.append(file_path.read_bytes())
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        headers = dict(self.headers)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self._request(method, path, data=b"".join(chunks), headers=headers, timeout=int(timeout or self.timeout))

    def _request(self, method: str, path: str, *, data: bytes | None, headers: dict[str, str], timeout: int) -> ApiResponse:
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = int(response.status)
        except HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except URLError as exc:
            return ApiResponse(status=0, body={"error": str(exc)}, elapsed_sec=time.perf_counter() - started)
        elapsed = time.perf_counter() - started
        text = raw.decode("utf-8", errors="replace")
        if not text:
            body: Any = None
        else:
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                body = text
        return ApiResponse(status=status, body=body, elapsed_sec=elapsed)


def ok_status(resp: ApiResponse) -> bool:
    return 200 <= int(resp.status) < 300


def snippet(body: Any, limit: int = 1200) -> str:
    if isinstance(body, str):
        return body[:limit]
    return json.dumps(body, ensure_ascii=False, default=str)[:limit]


def exported_document_ids(body: Any) -> list[str]:
    rows: list[dict[str, Any]] = []
    if isinstance(body, list):
        rows = [item for item in body if isinstance(item, dict)]
    elif isinstance(body, dict):
        for key in ("documents", "items", "results"):
            value = body.get(key)
            if isinstance(value, list):
                rows = [item for item in value if isinstance(item, dict)]
                break
    out: list[str] = []
    for row in rows:
        value = row.get("id") or row.get("document_id")
        text = str(value or "").strip()
        if text:
            out.append(text)
    return out


def citation_document_ids(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return []
    rows = body.get("citations")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("document_id") or "").strip()
        if text:
            out.append(text)
    return out


def response_text_from_body(body: Any) -> str:
    parts: list[str] = []
    if isinstance(body, dict):
        for key in ("response", "answer", "message", "content"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        citations = body.get("citations")
        if isinstance(citations, list):
            for item in citations:
                if not isinstance(item, dict):
                    continue
                for key in ("chunk_content", "content", "text", "snippet"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        parts.append(value.strip())
    elif isinstance(body, str) and body.strip():
        parts.append(body.strip())
    return "\n".join(parts)


def evaluate_boundary_case(
    case: dict[str, Any],
    *,
    citation_doc_ids: list[str],
    citation_count: int,
    response_text: str,
) -> list[str]:
    failures: list[str] = []
    name = str(case.get("name") or "case")
    actual_ids = [str(item) for item in citation_doc_ids if str(item).strip()]
    allowed_ids = [str(item) for item in (case.get("allowed_document_ids") or []) if str(item).strip()]
    expected_ids = [str(item) for item in (case.get("expected_document_ids") or []) if str(item).strip()]
    required_ids = [str(item) for item in (case.get("required_document_ids") or []) if str(item).strip()]
    expected_terms = [str(item) for item in (case.get("expected_terms") or []) if str(item).strip()]
    forbidden_terms = [str(item) for item in (case.get("forbidden_terms") or []) if str(item).strip()]

    if allowed_ids:
        leaked = [item for item in actual_ids if item not in allowed_ids]
        if leaked:
            failures.append(f"{name}: unexpected document_ids={leaked}")

    if case.get("expected_document_ids") is not None:
        if sorted(actual_ids) != sorted(expected_ids):
            failures.append(f"{name}: expected_document_ids={expected_ids} actual={actual_ids}")

    if required_ids:
        missing_ids = [item for item in required_ids if item not in actual_ids]
        if missing_ids:
            failures.append(f"{name}: required_document_ids missing={missing_ids} actual={actual_ids}")

    min_citations = case.get("min_citations")
    if min_citations is not None and int(citation_count) < int(min_citations):
        failures.append(f"{name}: min_citations={min_citations} actual={citation_count}")

    max_citations = case.get("max_citations")
    if max_citations is not None and int(citation_count) > int(max_citations):
        failures.append(f"{name}: max_citations={max_citations} actual={citation_count}")

    lowered = str(response_text or "").casefold()
    missing_terms = [term for term in expected_terms if term.casefold() not in lowered]
    if missing_terms:
        failures.append(f"{name}: missing expected_terms={missing_terms}")

    hit_forbidden = [term for term in forbidden_terms if term.casefold() in lowered]
    if hit_forbidden:
        failures.append(f"{name}: forbidden_terms={hit_forbidden}")

    return failures


def list_count(body: Any) -> int:
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        for key in ("items", "documents", "results", "citations", "chunks"):
            value = body.get(key)
            if isinstance(value, list):
                return len(value)
        for key in ("total", "count", "chunk_count"):
            value = body.get(key)
            if isinstance(value, int):
                return value
    return 0


def parsed_text_from_response(body: Any) -> str:
    if isinstance(body, str):
        return body
    if not isinstance(body, dict):
        return ""
    for key in ("markdown_content", "content", "text", "original_markdown_content"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def record_step(steps: list[dict[str, Any]], name: str, resp: ApiResponse, **extra: Any) -> None:
    item: dict[str, Any] = {
        "name": name,
        "status_code": int(resp.status),
        "elapsed_sec": round(float(resp.elapsed_sec), 3),
        "ok": ok_status(resp),
        **extra,
    }
    if not ok_status(resp):
        item["response"] = snippet(resp.body)
    steps.append(item)


def ensure_success(name: str, resp: ApiResponse) -> None:
    if not ok_status(resp):
        raise RuntimeError(f"{name} failed: HTTP {resp.status}: {snippet(resp.body)}")


def make_fixture_files(fixtures_dir: Path) -> dict[str, Path]:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    content = {
        "alpha-handbook.md": (
            "# Alpha Handbook\n\n"
            "Token ALOE-COMET belongs only to Dataset Alpha.\n\n"
            "Owner: Alice Meridian.\n"
            "Retention window: 14 days.\n"
            "This handbook must never appear in Dataset Beta retrieval.\n"
        ),
        "beta-runbook.md": (
            "# Beta Incident Runbook\n\n"
            "Token BETA-QUARTZ belongs only to Dataset Beta.\n\n"
            "Owner: Bob Quartz.\n"
            "Retention window: 30 days.\n"
            "This runbook must never appear in Dataset Alpha retrieval.\n"
        ),
    }
    out: dict[str, Path] = {}
    for name, text in content.items():
        path = fixtures_dir / name
        path.write_text(text, encoding="utf-8")
        out[name] = path
    return out


def wait_for_document_completed(
    api: LiveApi,
    *,
    steps: list[dict[str, Any]],
    filename: str,
    document_id: str,
    poll_timeout: int,
) -> dict[str, Any]:
    deadline = time.time() + int(poll_timeout)
    last_body: Any = None
    while time.time() < deadline:
        resp = api.json("GET", f"/api/v1/documents/{document_id}")
        last_body = resp.body
        record_step(steps, f"poll:{filename}", resp, doc_status=str((resp.body or {}).get("status") or ""))
        ensure_success(f"poll:{filename}", resp)
        status = str((resp.body or {}).get("status") or "").lower()
        if status in {"completed", "failed", "quarantined", "cancelled"}:
            break
        time.sleep(2)
    detail = dict(last_body or {})
    status = str(detail.get("status") or "").lower()
    if status != "completed":
        raise RuntimeError(f"{filename} did not complete: {snippet(detail)}")
    return detail


def perform_cleanup(api: LiveApi, *, steps: list[dict[str, Any]], dataset_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"dataset_id": dataset_id}
    resp = api.json("POST", f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000", payload={})
    record_step(steps, f"cleanup:purge:{dataset_id}", resp)
    ensure_success(f"cleanup purge {dataset_id}", resp)
    summary["purge_deleted"] = int((resp.body or {}).get("deleted") or 0) if isinstance(resp.body, dict) else 0

    resp = api.json("GET", f"/api/v1/datasets/{dataset_id}/documents/export?export_format=json&limit=20")
    remaining_ids = exported_document_ids(resp.body)
    record_step(steps, f"cleanup:export:{dataset_id}", resp, remaining_document_ids=remaining_ids)
    ensure_success(f"cleanup export {dataset_id}", resp)
    if remaining_ids:
        raise RuntimeError(f"documents remain after purge for {dataset_id}: {remaining_ids}")

    resp = api.json("DELETE", f"/api/v1/datasets/{dataset_id}")
    record_step(steps, f"cleanup:delete_dataset:{dataset_id}", resp)
    if not ok_status(resp) and int(resp.status) != 204:
        raise RuntimeError(f"delete dataset {dataset_id} failed: {snippet(resp.body)}")
    summary["delete_dataset_status"] = int(resp.status)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run knowledge-base dataset-boundary checks against a live API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-timeout", type=int, default=300)
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/kb-boundary-matrix/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixtures = make_fixture_files(artifact_dir / "fixtures")
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "base_url": args.base_url,
        "artifact_dir": str(artifact_dir),
        "datasets": {},
        "inventory_checks": [],
        "retrieve_checks": [],
        "chat_checks": [],
    }

    created_dataset_ids: list[str] = []

    try:
        resp = api.json("GET", "/api/v1/health")
        record_step(steps, "health", resp)
        ensure_success("health", resp)

        dataset_specs = {
            "alpha": {"name": f"KB Boundary Alpha {run_id}", "fixture": fixtures["alpha-handbook.md"]},
            "beta": {"name": f"KB Boundary Beta {run_id}", "fixture": fixtures["beta-runbook.md"]},
        }
        dataset_info: dict[str, dict[str, Any]] = {}

        for key, spec in dataset_specs.items():
            dataset_payload = {
                "name": spec["name"],
                "description": f"Knowledge-base boundary validation dataset ({key}).",
                "default_parser_backend": "auto",
                "default_chunk_strategy": "langchain_recursive",
                "pipeline": {
                    "governance_enabled": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "persist_parsed_content": True,
                    "persist_parsed_content_max_chars": 200000,
                    "chunk_size": 1200,
                    "chunk_overlap": 120,
                    "chunk_vector_enabled": True,
                    "bm25_index_enabled": True,
                    "kg_enabled": False,
                    "event_vector_enabled": False,
                    "entity_vector_enabled": False,
                },
                "rag_defaults": {
                    "top_k": 4,
                    "score_threshold": 0.0,
                    "retrieval_mode": "keyword",
                    "enable_reranker": False,
                    "enable_multi_query": False,
                    "enable_hyde": False,
                    "enable_query_decomposition": False,
                },
            }
            resp = api.json("POST", "/api/v1/datasets/", payload=dataset_payload)
            record_step(steps, f"create_dataset:{key}", resp)
            ensure_success(f"create_dataset:{key}", resp)
            dataset_id = str((resp.body or {}).get("id") or (resp.body or {}).get("dataset_id") or "")
            if not dataset_id:
                raise RuntimeError(f"create_dataset:{key} missing dataset id: {snippet(resp.body)}")
            created_dataset_ids.append(dataset_id)

            fields = {
                "dataset_id": dataset_id,
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "governance_enabled": "true",
                "chunk_vector_enabled": "true",
                "bm25_index_enabled": "true",
                "kg_enabled": "false",
                "event_vector_enabled": "false",
                "entity_vector_enabled": "false",
            }
            resp = api.multipart("POST", "/api/v1/documents/upload", fields=fields, file_path=Path(spec["fixture"]))
            record_step(steps, f"upload:{key}", resp)
            ensure_success(f"upload:{key}", resp)
            document_id = str((resp.body or {}).get("id") or (resp.body or {}).get("document_id") or "")
            if not document_id:
                raise RuntimeError(f"upload:{key} missing document id: {snippet(resp.body)}")

            detail = wait_for_document_completed(api, steps=steps, filename=key, document_id=document_id, poll_timeout=args.poll_timeout)
            chunks_resp = api.json("GET", f"/api/v1/documents/{document_id}/chunks?limit=200")
            record_step(steps, f"chunks:{key}", chunks_resp, chunk_count=list_count(chunks_resp.body))
            ensure_success(f"chunks:{key}", chunks_resp)
            parsed_resp = api.json("GET", f"/api/v1/documents/{document_id}/parsed-content?max_chars=8000")
            record_step(steps, f"parsed:{key}", parsed_resp, parsed_chars=len(parsed_text_from_response(parsed_resp.body)))
            ensure_success(f"parsed:{key}", parsed_resp)

            dataset_info[key] = {
                "dataset_id": dataset_id,
                "document_id": document_id,
                "status": str(detail.get("status") or "").lower(),
                "chunk_count": list_count(chunks_resp.body),
                "parsed_chars": len(parsed_text_from_response(parsed_resp.body)),
            }

        summary["datasets"] = dataset_info

        for key, info in dataset_info.items():
            resp = api.json("GET", f"/api/v1/datasets/{info['dataset_id']}/documents/export?export_format=json&limit=20")
            export_ids = exported_document_ids(resp.body)
            record_step(steps, f"inventory_export:{key}", resp, document_ids=export_ids)
            ensure_success(f"inventory_export:{key}", resp)
            ok = export_ids == [info["document_id"]]
            summary["inventory_checks"].append(
                {
                    "name": f"dataset_{key}_inventory",
                    "status_code": resp.status,
                    "ok": ok,
                    "expected_document_ids": [info["document_id"]],
                    "actual_document_ids": export_ids,
                }
            )
            if not ok:
                raise RuntimeError(f"dataset inventory mismatch for {key}: {export_ids}")

        retrieve_cases = [
            {
                "name": "dataset_alpha_positive",
                "query": "Who owns token ALOE-COMET?",
                "dataset_id": dataset_info["alpha"]["dataset_id"],
                "allowed_document_ids": [dataset_info["alpha"]["document_id"]],
                "expected_document_ids": [dataset_info["alpha"]["document_id"]],
                "expected_terms": ["ALOE-COMET"],
                "min_citations": 1,
            },
            {
                "name": "dataset_alpha_negative_beta_query",
                "query": "Who owns token BETA-QUARTZ?",
                "dataset_id": dataset_info["alpha"]["dataset_id"],
                "allowed_document_ids": [dataset_info["alpha"]["document_id"]],
                "forbidden_terms": ["Bob Quartz", "BETA-QUARTZ"],
            },
            {
                "name": "dataset_beta_positive",
                "query": "Who owns token BETA-QUARTZ?",
                "dataset_id": dataset_info["beta"]["dataset_id"],
                "allowed_document_ids": [dataset_info["beta"]["document_id"]],
                "expected_document_ids": [dataset_info["beta"]["document_id"]],
                "expected_terms": ["BETA-QUARTZ"],
                "min_citations": 1,
            },
            {
                "name": "cross_dataset_beta_positive",
                "query": "Who owns token BETA-QUARTZ?",
                "document_ids": [dataset_info["alpha"]["document_id"], dataset_info["beta"]["document_id"]],
                "allowed_document_ids": [dataset_info["alpha"]["document_id"], dataset_info["beta"]["document_id"]],
                "required_document_ids": [dataset_info["beta"]["document_id"]],
                "expected_terms": ["BETA-QUARTZ"],
                "min_citations": 1,
            },
        ]

        rag_config = {
            "top_k": 4,
            "score_threshold": 0.0,
            "retrieval_mode": "keyword",
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
        }

        for case in retrieve_cases:
            payload = {
                "query": case["query"],
                "rag_config": rag_config,
            }
            if case.get("dataset_id"):
                payload["dataset_id"] = case["dataset_id"]
            if case.get("document_ids"):
                payload["document_ids"] = case["document_ids"]
            resp = api.json("POST", "/api/v1/rag/retrieve-preview", payload=payload)
            record_step(steps, f"retrieve:{case['name']}", resp, citation_count=list_count(resp.body))
            ensure_success(f"retrieve:{case['name']}", resp)
            citation_ids = citation_document_ids(resp.body)
            text = response_text_from_body(resp.body)
            failures = evaluate_boundary_case(
                case,
                citation_doc_ids=citation_ids,
                citation_count=list_count(resp.body),
                response_text=text,
            )
            row = {
                "name": case["name"],
                "status_code": resp.status,
                "ok": not failures,
                "citation_document_ids": citation_ids,
                "citation_count": list_count(resp.body),
                "response_preview": text[:300],
                "failures": failures,
            }
            summary["retrieve_checks"].append(row)
            if failures:
                raise RuntimeError(f"retrieve case failed {case['name']}: {failures}")

        chat_cases = [
            {
                "name": "dataset_alpha_chat_positive",
                "message": "Who owns token ALOE-COMET?",
                "dataset_id": dataset_info["alpha"]["dataset_id"],
                "allowed_document_ids": [dataset_info["alpha"]["document_id"]],
                "expected_document_ids": [dataset_info["alpha"]["document_id"]],
                "expected_terms": ["ALOE-COMET"],
                "min_citations": 1,
            },
            {
                "name": "cross_dataset_beta_chat_positive",
                "message": "Who owns token BETA-QUARTZ?",
                "document_ids": [dataset_info["alpha"]["document_id"], dataset_info["beta"]["document_id"]],
                "allowed_document_ids": [dataset_info["alpha"]["document_id"], dataset_info["beta"]["document_id"]],
                "required_document_ids": [dataset_info["beta"]["document_id"]],
                "expected_terms": ["BETA-QUARTZ"],
                "min_citations": 1,
            },
        ]

        for case in chat_cases:
            payload = {
                "message": case["message"],
                "stream": False,
                "rag_config": {
                    **rag_config,
                    "answer_mode": "extractive",
                    "max_tokens": 400,
                },
            }
            if case.get("dataset_id"):
                payload["dataset_id"] = case["dataset_id"]
            if case.get("document_ids"):
                payload["document_ids"] = case["document_ids"]
            resp = api.json("POST", "/api/v1/chat", payload=payload)
            record_step(steps, f"chat:{case['name']}", resp, citation_count=list_count(resp.body))
            ensure_success(f"chat:{case['name']}", resp)
            citation_ids = citation_document_ids(resp.body)
            text = response_text_from_body(resp.body)
            failures = evaluate_boundary_case(
                case,
                citation_doc_ids=citation_ids,
                citation_count=list_count((resp.body or {}).get("citations") if isinstance(resp.body, dict) else resp.body),
                response_text=text,
            )
            row = {
                "name": case["name"],
                "status_code": resp.status,
                "ok": not failures,
                "citation_document_ids": citation_ids,
                "citation_count": list_count((resp.body or {}).get("citations") if isinstance(resp.body, dict) else resp.body),
                "answer_preview": text[:300],
                "failures": failures,
            }
            summary["chat_checks"].append(row)
            if failures:
                raise RuntimeError(f"chat case failed {case['name']}: {failures}")

        cleanup: dict[str, Any] = {}
        for key, info in dataset_info.items():
            cleanup[key] = perform_cleanup(api, steps=steps, dataset_id=info["dataset_id"])
        summary["cleanup"] = cleanup
        summary["ok"] = True
        return_code = 0
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
        return_code = 1
    finally:
        report = {"summary": summary, "steps": steps}
        (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
