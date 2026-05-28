#!/usr/bin/env python3
"""Lightweight live API chain smoke test.

This script intentionally uses only the Python standard library so it can run on
production hosts and inside minimal containers without installing test-only
dependencies.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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
        self.timeout = timeout
        self.headers = {
            "X-Tenant-ID": tenant_id,
            "X-Account-ID": account_id,
            "X-User-ID": user_id,
        }

    def json(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> ApiResponse:
        data = None
        headers = dict(self.headers)
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self._request(method, path, data=data, headers=headers)

    def multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        file_field: str = "file",
    ) -> ApiResponse:
        boundary = f"----MimirQSmoke{uuid.uuid4().hex}"
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
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode()
        )
        chunks.append(file_path.read_bytes())
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        headers = dict(self.headers)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self._request(method, path, data=b"".join(chunks), headers=headers)

    def _request(self, method: str, path: str, *, data: bytes | None, headers: dict[str, str]) -> ApiResponse:
        url = f"{self.base_url}{path}"
        req = Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = int(resp.status)
        except HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except URLError as exc:
            elapsed = time.perf_counter() - started
            return ApiResponse(status=0, body={"error": str(exc)}, elapsed_sec=elapsed)
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
    return 200 <= resp.status < 300


def snippet(body: Any, limit: int = 800) -> str:
    if isinstance(body, str):
        return body[:limit]
    return json.dumps(body, ensure_ascii=False, default=str)[:limit]


def record_step(steps: list[dict[str, Any]], name: str, resp: ApiResponse | None = None, **extra: Any) -> None:
    item: dict[str, Any] = {"name": name, **extra}
    if resp is not None:
        item.update({"status_code": resp.status, "elapsed_sec": round(resp.elapsed_sec, 3), "ok": ok_status(resp)})
        if not ok_status(resp):
            item["response"] = snippet(resp.body)
    steps.append(item)


def make_fixtures(fixtures_dir: Path) -> dict[str, Path]:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    content = {
        "remote-ops-brief.md": (
            "# Remote RAG Operations Brief\n\n"
            "MimirQ is a knowledge ingestion and retrieval system. The production proof must verify parsing, "
            "governance, chunking, vector indexing, BM25 indexing, graph extraction, and answer grounding.\n\n"
            "## Incident Playbook\n\n"
            "When API latency exceeds 800 ms, inspect PostgreSQL, Milvus, Redis, parser workers, and queue depth. "
            "The primary owner records the dataset id, document id, request id, and parser backend used for each run.\n\n"
            "## POC Pricing Notes\n\n"
            "A data batch is difficult when it has many scanned PDFs, long average pages, dense tables, repeated "
            "watermarks, or mixed Office formats. The recommended precheck samples at least one file per file type "
            "and adds proportional samples for large batches.\n\n"
            "## KG Policy\n\n"
            "The knowledge graph is a sparse support index. It extracts important entities and events, not every "
            "sentence. RAG retrieval remains the main evidence path.\n"
        ),
        "remote-governance.html": (
            "<!doctype html><html><body><h1>Governance Checklist</h1>"
            "<p>Remove boilerplate, page headers, tracking text, and duplicated footers before chunking.</p>"
            "<table><tr><th>Rule</th><th>Purpose</th></tr>"
            "<tr><td>PII redaction</td><td>Protect emails and phone numbers.</td></tr>"
            "<tr><td>Markdown normalization</td><td>Keep headings and tables stable.</td></tr></table>"
            "<p>Contact: demo@example.com should be masked by governance when configured.</p>"
            "</body></html>"
        ),
        "remote-metrics.csv": (
            "metric,value,owner\n"
            "latency_p95_ms,720,platform\n"
            "parser_success_rate,0.99,ingestion\n"
            "retrieval_mrr,0.74,rag\n"
            "kg_event_budget,120,graph\n"
        ),
        "remote-faq.json": json.dumps(
            {
                "question": "How should KG be used in MimirQ?",
                "answer": "Use KG as a sparse relation and event support index for RAG, not as the only answer generator.",
                "tags": ["kg", "rag", "events"],
            },
            ensure_ascii=False,
            indent=2,
        ),
    }
    paths: dict[str, Path] = {}
    for name, text in content.items():
        path = fixtures_dir / name
        path.write_text(text, encoding="utf-8")
        paths[name] = path
    return paths


def ensure_success(name: str, resp: ApiResponse) -> None:
    if not ok_status(resp):
        raise RuntimeError(f"{name} failed: HTTP {resp.status}: {snippet(resp.body)}")


def list_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("items", "chunks", "results", "documents", "citations"):
            item = value.get(key)
            if isinstance(item, list):
                return len(item)
        for key in ("total", "count", "chunk_count"):
            item = value.get(key)
            if isinstance(item, int):
                return item
    return 0


def parsed_text_from_response(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for key in ("markdown_content", "content", "text", "original_markdown_content"):
        text = value.get(key)
        if isinstance(text, str) and text:
            return text
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live MimirQ API chain smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-timeout", type=int, default=360)
    parser.add_argument("--skip-chat", action="store_true")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/remote-api-chain/remote-api-chain-{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixtures = make_fixtures(artifact_dir / "fixtures")
    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"ok": False, "artifact_dir": str(artifact_dir), "base_url": args.base_url}

    try:
        resp = api.json("GET", "/api/v1/health")
        record_step(steps, "health", resp)
        ensure_success("health", resp)

        dataset_payload = {
            "name": f"Remote API Chain {run_id}",
            "description": "Automated live chain verification for parser, chunking, KG and RAG.",
            "default_parser_backend": "auto",
            "default_chunk_strategy": "langchain_recursive",
            "pipeline": {
                "governance_enabled": True,
                "governance_remove_noise_lines": True,
                "governance_unwrap_lines": True,
                "governance_drop_duplicate_paragraphs": True,
                "persist_parsed_content": True,
                "persist_parsed_content_max_chars": 500000,
                "chunk_size": 1600,
                "chunk_overlap": 160,
                "chunk_vector_enabled": True,
                "bm25_index_enabled": True,
                "kg_enabled": False,
                "event_vector_enabled": False,
                "entity_vector_enabled": False,
            },
            "rag_defaults": {
                "top_k": 6,
                "score_threshold": 0.0,
                "retrieval_mode": "hybrid",
                "enable_reranker": False,
                "enable_multi_query": False,
                "enable_hyde": False,
                "enable_query_decomposition": False,
            },
        }
        resp = api.json("POST", "/api/v1/datasets/", payload=dataset_payload)
        record_step(steps, "create_dataset", resp)
        ensure_success("create_dataset", resp)
        dataset_id = str((resp.body or {}).get("id") or (resp.body or {}).get("dataset_id") or "")
        if not dataset_id:
            raise RuntimeError(f"create_dataset response missing id: {snippet(resp.body)}")

        uploaded: list[dict[str, Any]] = []
        for filename, path in fixtures.items():
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
            resp = api.multipart("POST", "/api/v1/documents/upload", fields=fields, file_path=path)
            record_step(steps, f"upload:{filename}", resp)
            ensure_success(f"upload:{filename}", resp)
            uploaded.append(
                {
                    "filename": filename,
                    "document_id": str((resp.body or {}).get("id") or (resp.body or {}).get("document_id") or ""),
                    "upload_sec": round(resp.elapsed_sec, 3),
                }
            )

        documents: list[dict[str, Any]] = []
        for item in uploaded:
            document_id = item["document_id"]
            deadline = time.time() + args.poll_timeout
            detail: Any = None
            while time.time() < deadline:
                resp = api.json("GET", f"/api/v1/documents/{document_id}")
                record_step(steps, f"poll:{item['filename']}", resp)
                ensure_success(f"poll:{item['filename']}", resp)
                detail = resp.body or {}
                status = str(detail.get("status") or "").lower()
                if status in {"completed", "failed", "quarantined", "cancelled"}:
                    break
                time.sleep(2)
            status = str((detail or {}).get("status") or "").lower()
            if status != "completed":
                raise RuntimeError(f"document {document_id} did not complete, status={status}: {snippet(detail)}")
            chunks_resp = api.json("GET", f"/api/v1/documents/{document_id}/chunks?limit=2000")
            record_step(steps, f"chunks:{item['filename']}", chunks_resp)
            ensure_success(f"chunks:{item['filename']}", chunks_resp)
            parsed_resp = api.json("GET", f"/api/v1/documents/{document_id}/parsed-content?max_chars=20000")
            record_step(steps, f"parsed:{item['filename']}", parsed_resp)
            parsed_text = parsed_text_from_response(parsed_resp.body) if ok_status(parsed_resp) else ""
            documents.append(
                {
                    "filename": item["filename"],
                    "document_id": document_id,
                    "status": status,
                    "chunks": list_count(chunks_resp.body),
                    "parsed_chars": len(parsed_text),
                }
            )

        preview_cases = [
            ("langchain_recursive", fixtures["remote-ops-brief.md"]),
            ("markdown_hierarchy", fixtures["remote-ops-brief.md"]),
            ("semantic_sentence", fixtures["remote-governance.html"]),
            ("csv_rows", fixtures["remote-metrics.csv"]),
            ("parent_child", fixtures["remote-ops-brief.md"]),
        ]
        previews: list[dict[str, Any]] = []
        for strategy, path in preview_cases:
            fields = {
                "dataset_id": dataset_id,
                "parser_backend": "auto",
                "chunk_strategy": strategy,
                "chunk_size": "1200",
                "chunk_overlap": "120",
                "include_original_text": "false",
                "include_chunks": "true",
                "max_chunks": "80",
            }
            resp = api.multipart("POST", "/api/v1/documents/chunk-preview", fields=fields, file_path=path)
            record_step(steps, f"chunk_preview:{strategy}", resp)
            previews.append(
                {
                    "strategy": strategy,
                    "status_code": resp.status,
                    "ok": ok_status(resp),
                    "chunks": list_count(resp.body),
                    "elapsed_sec": round(resp.elapsed_sec, 3),
                    "error": None if ok_status(resp) else snippet(resp.body),
                }
            )

        kg_results: list[dict[str, Any]] = []
        for item in documents:
            if item["filename"].endswith(".csv"):
                continue
            params = urlencode(
                {
                    "replace_existing": "true",
                    "extract_relations": "false",
                    "extract_skills": "false",
                    "extraction_backend": "heuristic",
                }
            )
            resp = api.json("POST", f"/api/v1/kg/documents/{item['document_id']}/extract?{params}")
            record_step(steps, f"kg_extract:{item['filename']}", resp)
            kg_results.append(
                {
                    "filename": item["filename"],
                    "document_id": item["document_id"],
                    "status_code": resp.status,
                    "ok": ok_status(resp),
                    "elapsed_sec": round(resp.elapsed_sec, 3),
                    "error": None if ok_status(resp) else snippet(resp.body),
                }
            )
        resp = api.json("GET", f"/api/v1/kg/stats?dataset_id={dataset_id}")
        record_step(steps, "kg_stats", resp)
        kg_stats_status = resp.status
        kg_stats = resp.body
        resp = api.json(
            "POST",
            "/api/v1/kg/search",
            payload={"query": "MimirQ RAG KG event support index", "dataset_id": dataset_id},
        )
        record_step(steps, "kg_search", resp)
        kg_search_status = resp.status

        retrieve_payload = {
            "query": "MimirQ KG role in RAG support index",
            "dataset_id": dataset_id,
            "rag_config": {
                "top_k": 6,
                "score_threshold": 0.0,
                "retrieval_mode": "hybrid",
                "enable_reranker": False,
                "enable_multi_query": False,
                "enable_hyde": False,
                "enable_query_decomposition": False,
            },
        }
        resp = api.json("POST", "/api/v1/rag/retrieve-preview", payload=retrieve_payload)
        record_step(steps, "rag_retrieve_preview", resp)
        rag_retrieve_count = list_count(resp.body)

        chat_status: int | None = None
        chat_elapsed_sec: float | None = None
        chat_answer = ""
        if not args.skip_chat:
            chat_payload = {
                "message": "Explain in two sentences how MimirQ should use KG with RAG, citing one detail from the dataset.",
                "dataset_id": dataset_id,
                "stream": False,
                "rag_config": {
                    "top_k": 6,
                    "score_threshold": 0.0,
                    "retrieval_mode": "hybrid",
                    "use_graph": True,
                    "enable_reranker": False,
                    "enable_multi_query": False,
                    "enable_hyde": False,
                    "enable_query_decomposition": False,
                    "max_tokens": 700,
                    "answer_mode": "extractive",
                },
            }
            resp = api.json("POST", "/api/v1/chat", payload=chat_payload)
            record_step(steps, "chat", resp)
            chat_status = resp.status
            chat_elapsed_sec = round(resp.elapsed_sec, 3)
            if isinstance(resp.body, dict):
                chat_answer = str(
                    resp.body.get("response")
                    or resp.body.get("answer")
                    or resp.body.get("message")
                    or resp.body.get("content")
                    or ""
                )

        summary.update(
            {
                "ok": (
                    all(item["status"] == "completed" for item in documents)
                    and all(item["ok"] for item in previews)
                    and all(item["ok"] for item in kg_results)
                    and 200 <= kg_stats_status < 300
                    and 200 <= kg_search_status < 300
                    and rag_retrieve_count > 0
                    and (args.skip_chat or bool(chat_answer.strip()))
                ),
                "dataset_id": dataset_id,
                "documents": documents,
                "chunk_preview": previews,
                "kg_extract": kg_results,
                "kg_stats_status": kg_stats_status,
                "kg_stats": kg_stats,
                "kg_search_status": kg_search_status,
                "rag_retrieve_count": rag_retrieve_count,
                "chat_status": chat_status,
                "chat_elapsed_sec": chat_elapsed_sec,
                "chat_answer_preview": chat_answer[:500],
            }
        )
    except Exception as exc:  # noqa: BLE001 - smoke test should persist all diagnostics.
        summary.update({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
    finally:
        summary["steps"] = steps
        (artifact_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            f"# Remote API Chain {run_id}",
            "",
            f"- ok: `{summary.get('ok')}`",
            f"- artifact: `{artifact_dir}`",
            f"- dataset_id: `{summary.get('dataset_id', '-')}`",
            f"- documents: `{len(summary.get('documents') or [])}`",
            f"- rag_retrieve_count: `{summary.get('rag_retrieve_count', '-')}`",
            f"- chat_status: `{summary.get('chat_status', '-')}`",
            f"- errors: `{1 if summary.get('error') else 0}`",
            "",
            "## Steps",
        ]
        for item in steps:
            lines.append(
                f"- {item.get('name')}: ok={item.get('ok')} "
                f"status={item.get('status_code', '-')} elapsed={item.get('elapsed_sec', '-')}"
            )
        if summary.get("error"):
            lines.extend(["", "## Error", "```", str(summary["error"]), "```"])
        if summary.get("chat_answer_preview"):
            lines.extend(["", "## Chat Preview", str(summary["chat_answer_preview"])])
        (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    key: summary.get(key)
                    for key in (
                        "ok",
                        "artifact_dir",
                        "dataset_id",
                        "rag_retrieve_count",
                        "chat_status",
                        "chat_elapsed_sec",
                        "error",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
