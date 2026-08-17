#!/usr/bin/env python3
"""Run a real-PDF parse -> chunk -> KG -> chat verification chain.

This script intentionally uses only the Python standard library so it can run
on production-like hosts without extra dependencies.
"""

import argparse
import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
DOCUMENT_CHUNK_LIST_LIMIT = 2000
DEFAULT_KG_QUERIES = ["What is this paper about"]
DEFAULT_CHAT_QUESTIONS = ["Summarize what this paper says about large language models in two sentences."]
DEFAULT_CHUNK_STRATEGIES = (
    "langchain_recursive",
    "parent_child",
    "semantic_sentence",
    "markdown_hierarchy",
)
TERMINAL_DOCUMENT_STATUSES = {"completed", "failed", "quarantined", "cancelled"}


class LiveApi:
    def __init__(
        self,
        base_url: str,
        tenant_id: str,
        account_id: str,
        user_id: str,
        timeout: int,
    ) -> None:
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
    ) -> tuple[int, Any, float]:
        headers = dict(self.headers)
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request(
            method,
            path,
            data=data,
            headers=headers,
            timeout=int(timeout or self.timeout),
        )

    def multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        timeout: int | None = None,
    ) -> tuple[int, Any, float]:
        boundary = f"----MimirQRealPdf{uuid.uuid4().hex}"
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

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None,
        headers: dict[str, str],
        timeout: int,
    ) -> tuple[int, Any, float]:
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
            return 0, {"error": str(exc)}, time.perf_counter() - started
        elapsed = time.perf_counter() - started
        text = raw.decode("utf-8", errors="replace")
        if not text:
            return status, None, elapsed
        try:
            return status, json.loads(text), elapsed
        except json.JSONDecodeError:
            return status, text, elapsed


def ok_status(status_code: int) -> bool:
    return 200 <= int(status_code) < 300


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


def snippet(body: Any, limit: int = 2000) -> str:
    if isinstance(body, str):
        return body[:limit]
    return json.dumps(body, ensure_ascii=False, default=str)[:limit]


def effective_questions(cli_values: list[str] | None, defaults: list[str]) -> list[str]:
    values = [str(item).strip() for item in (cli_values or []) if str(item).strip()]
    return values or list(defaults)


def download(url: str, target: Path, timeout: int) -> dict[str, Any]:
    if target.exists() and target.stat().st_size > 0:
        return {"url": url, "path": str(target), "bytes": target.stat().st_size, "cached": True}
    request = Request(url, headers={"User-Agent": "MimirQ real PDF chain"})
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    target.write_bytes(data)
    return {
        "url": url,
        "path": str(target),
        "bytes": len(data),
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "cached": False,
    }


def record_step(steps: list[dict[str, Any]], name: str, status: int, body: Any, elapsed: float, **extra: Any) -> None:
    item = {"name": name, "status_code": int(status), "elapsed_sec": round(float(elapsed), 3), **extra}
    if not ok_status(status):
        item["response"] = snippet(body)
    steps.append(item)


def cleanup_mode_value(cleanup_mode: str) -> str:
    mode = (cleanup_mode or "none").strip().lower() or "none"
    return mode if mode in {"none", "delete_document", "purge_dataset"} else "none"


def cleanup_step(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    name: str,
    method: str,
    path: str,
    timeout: int,
    payload: dict[str, Any] | None = None,
    **extra: Any,
) -> tuple[int, Any]:
    status, body, elapsed = api.json(method, path, payload=payload, timeout=timeout)
    record_step(steps, name, status, body, elapsed, **extra)
    return status, body


def verify_cleanup_documents_removed(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    dataset_id: str,
    summary: dict[str, Any],
    timeout: int,
) -> None:
    status, body = cleanup_step(
        api,
        steps,
        name="cleanup:dataset_documents_export",
        method="GET",
        path=f"/api/v1/datasets/{dataset_id}/documents/export?export_format=json&limit=10",
        timeout=min(int(timeout), 120),
    )
    remaining = list_count(body)
    steps[-1]["remaining_documents"] = remaining
    summary["post_cleanup_document_count"] = int(remaining)
    if not ok_status(status):
        raise RuntimeError(f"dataset documents export failed: {snippet(body)}")
    if remaining > 0:
        raise RuntimeError(f"documents remain after cleanup: {remaining}")


def verify_cleanup_kg_removed(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    dataset_id: str,
    summary: dict[str, Any],
    timeout: int,
) -> None:
    status, body = cleanup_step(
        api,
        steps,
        name="cleanup:kg_stats",
        method="GET",
        path=f"/api/v1/kg/stats?dataset_id={dataset_id}",
        timeout=min(int(timeout), 120),
    )
    summary["post_cleanup_kg_stats"] = body
    if not ok_status(status):
        raise RuntimeError(f"kg stats after cleanup failed: {snippet(body)}")
    if isinstance(body, dict) and any(int(body.get(key) or 0) > 0 for key in ("events", "entities", "links")):
        raise RuntimeError(f"kg artifacts remain after cleanup: {snippet(body)}")


def maybe_delete_dataset_after_cleanup(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    dataset_id: str,
    summary: dict[str, Any],
    delete_dataset_after: bool,
    timeout: int,
) -> None:
    if not bool(delete_dataset_after):
        return
    status, body = cleanup_step(
        api,
        steps,
        name="cleanup:delete_dataset",
        method="DELETE",
        path=f"/api/v1/datasets/{dataset_id}",
        timeout=timeout,
    )
    summary["delete_dataset_status"] = int(status)
    if not ok_status(status) and int(status) != 204:
        raise RuntimeError(f"delete dataset failed: {snippet(body)}")


def perform_cleanup(
    *,
    api: LiveApi,
    steps: list[dict[str, Any]],
    dataset_id: str,
    document_id: str,
    cleanup_mode: str,
    delete_dataset_after: bool,
    timeout: int,
) -> dict[str, Any]:
    mode = cleanup_mode_value(cleanup_mode)
    summary: dict[str, Any] = {"mode": mode}
    if mode == "none":
        return summary

    if mode == "delete_document":
        status, body = cleanup_step(
            api,
            steps,
            name="cleanup:delete_document",
            method="DELETE",
            path=f"/api/v1/documents/{document_id}",
            timeout=timeout,
        )
        summary["delete_document_status"] = int(status)
        if not ok_status(status) and int(status) != 204:
            raise RuntimeError(f"delete document failed: {snippet(body)}")
    elif mode == "purge_dataset":
        status, body = cleanup_step(
            api,
            steps,
            name="cleanup:purge_dataset",
            method="POST",
            path=f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000",
            timeout=timeout,
            payload={},
        )
        summary["purge_status"] = int(status)
        summary["purge_deleted"] = int((body or {}).get("deleted") or 0) if isinstance(body, dict) else 0
        if not ok_status(status):
            raise RuntimeError(f"purge dataset failed: {snippet(body)}")

    verify_cleanup_documents_removed(
        api,
        steps,
        dataset_id=dataset_id,
        summary=summary,
        timeout=timeout,
    )
    verify_cleanup_kg_removed(
        api,
        steps,
        dataset_id=dataset_id,
        summary=summary,
        timeout=timeout,
    )
    maybe_delete_dataset_after_cleanup(
        api,
        steps,
        dataset_id=dataset_id,
        summary=summary,
        delete_dataset_after=delete_dataset_after,
        timeout=timeout,
    )

    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Run a real-PDF parse -> chunk -> KG -> chat chain against a live MimirQ API.")
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--pdf-url", default="")
    parser.add_argument("--pdf-path", default="")
    parser.add_argument("--filename", default="large-paper.pdf")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--parser-backend", default="magicpdf")
    parser.add_argument(
        "--chunk-strategies",
        default=",".join(DEFAULT_CHUNK_STRATEGIES),
    )
    parser.add_argument("--kg-backend", default="")
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--download-timeout", type=int, default=300)
    parser.add_argument("--poll-timeout", type=int, default=7200)
    parser.add_argument("--skip-kg", action="store_true")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument(
        "--kg-query",
        action="append",
        default=[],
        help="Repeatable KG search query override",
    )
    parser.add_argument(
        "--chat-question",
        action="append",
        default=[],
        help="Repeatable chat question override",
    )
    parser.add_argument("--cleanup-mode", default="none")
    parser.add_argument("--delete-dataset-after", action="store_true")
    return parser


def create_run_artifacts(
    args: argparse.Namespace,
    *,
    run_id: str,
) -> tuple[Path, Path, dict[str, Any]]:
    artifact_dir = Path(args.artifact_dir or f"artifacts/real-pdf-chain/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(args.pdf_path).resolve() if args.pdf_path else artifact_dir / args.filename
    source: dict[str, Any] = {"path": str(pdf_path)}
    if args.pdf_url:
        source = download(args.pdf_url, pdf_path, timeout=int(args.download_timeout))
    elif not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))
    return artifact_dir, pdf_path, source


def create_dataset(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    parser_backend: str,
    run_id: str,
) -> str:
    status, body, elapsed = api.json(
        "POST",
        "/api/v1/datasets/",
        payload={
            "name": f"Real PDF Chain {run_id}",
            "description": "Large real PDF parse/chunk/kg/rag verification",
            "default_parser_backend": parser_backend,
            "default_chunk_strategy": "langchain_recursive",
            "pipeline": {
                "governance_enabled": True,
                "governance_remove_noise_lines": True,
                "governance_unwrap_lines": True,
                "governance_drop_duplicate_paragraphs": True,
                "persist_parsed_content": True,
                "persist_parsed_content_max_chars": 900000,
                "chunk_size": 1600,
                "chunk_overlap": 160,
                "chunk_vector_enabled": True,
                "bm25_index_enabled": True,
                "kg_enabled": False,
                "event_vector_enabled": False,
                "entity_vector_enabled": False,
            },
        },
    )
    record_step(steps, "create_dataset", status, body, elapsed)
    if not ok_status(status):
        raise RuntimeError(f"create_dataset failed: {snippet(body)}")
    dataset_id = str((body or {}).get("id") or (body or {}).get("dataset_id") or "")
    if not dataset_id:
        raise RuntimeError(f"create_dataset response missing id: {snippet(body)}")
    return dataset_id


def upload_document(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    dataset_id: str,
    parser_backend: str,
    pdf_path: Path,
    timeout: int,
) -> str:
    fields = {
        "dataset_id": dataset_id,
        "parser_backend": parser_backend,
        "chunk_strategy": "langchain_recursive",
        "governance_enabled": "true",
        "chunk_vector_enabled": "true",
        "bm25_index_enabled": "true",
        "kg_enabled": "false",
        "event_vector_enabled": "false",
        "entity_vector_enabled": "false",
    }
    status, body, elapsed = api.multipart(
        "POST",
        "/api/v1/documents/upload",
        fields=fields,
        file_path=pdf_path,
        timeout=timeout,
    )
    record_step(steps, "upload", status, body, elapsed)
    if not ok_status(status):
        raise RuntimeError(f"upload failed: {snippet(body)}")
    document_id = str((body or {}).get("id") or (body or {}).get("document_id") or "")
    if not document_id:
        raise RuntimeError(f"upload response missing document_id: {snippet(body)}")
    return document_id


def poll_document_until_complete(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    document_id: str,
    timeout: int,
    poll_timeout: int,
) -> tuple[str, Any]:
    deadline = time.time() + int(poll_timeout)
    last_body: Any = None
    while time.time() < deadline:
        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/documents/{document_id}",
            timeout=timeout,
        )
        last_body = body
        record_step(
            steps,
            "poll_document",
            status,
            body,
            elapsed,
            doc_status=str((body or {}).get("status") or ""),
        )
        if not ok_status(status):
            raise RuntimeError(f"document poll failed: {snippet(body)}")
        doc_status = str((body or {}).get("status") or "").lower()
        if doc_status in TERMINAL_DOCUMENT_STATUSES:
            break
        time.sleep(5)
    final_status = str((last_body or {}).get("status") or "").lower()
    return final_status, last_body


def fetch_chunk_count(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    document_id: str,
    timeout: int,
) -> int:
    status, body, elapsed = api.json(
        "GET",
        f"/api/v1/documents/{document_id}/chunks?limit={DOCUMENT_CHUNK_LIST_LIMIT}",
        timeout=timeout,
    )
    chunk_count = list_count(body)
    record_step(steps, "chunks", status, body, elapsed, chunk_count=chunk_count)
    if not ok_status(status):
        raise RuntimeError(f"chunks failed: {snippet(body)}")
    return chunk_count


def fetch_parsed_chars(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    document_id: str,
    timeout: int,
) -> int:
    status, body, elapsed = api.json(
        "GET",
        f"/api/v1/documents/{document_id}/parsed-content?max_chars=50000",
        timeout=timeout,
    )
    parsed_text = parsed_text_from_response(body)
    parsed_chars = len(parsed_text)
    record_step(
        steps,
        "parsed_content",
        status,
        body,
        elapsed,
        parsed_chars=parsed_chars,
    )
    return parsed_chars


def chunk_preview_strategies(chunk_strategies: str) -> list[str]:
    return [item.strip() for item in str(chunk_strategies or "").split(",") if item.strip()]


def build_chunk_preview_fields(
    *,
    dataset_id: str,
    parser_backend: str,
    strategy: str,
) -> dict[str, str]:
    return {
        "dataset_id": dataset_id,
        "parser_backend": parser_backend,
        "chunk_strategy": strategy,
        "chunk_size": "1600",
        "chunk_overlap": "160",
        "include_original_text": "false",
        "include_chunks": "true",
        "max_chunks": "120",
    }


def run_chunk_previews(
    api: LiveApi,
    steps: list[dict[str, Any]],
    *,
    chunk_strategies: str,
    dataset_id: str,
    parser_backend: str,
    pdf_path: Path,
    timeout: int,
) -> list[dict[str, Any]]:
    preview_rows: list[dict[str, Any]] = []
    for strategy in chunk_preview_strategies(chunk_strategies):
        status, body, elapsed = api.multipart(
            "POST",
            "/api/v1/documents/chunk-preview",
            fields=build_chunk_preview_fields(
                dataset_id=dataset_id,
                parser_backend=parser_backend,
                strategy=strategy,
            ),
            file_path=pdf_path,
            timeout=timeout,
        )
        count = list_count(body)
        record_step(
            steps,
            f"chunk_preview:{strategy}",
            status,
            body,
            elapsed,
            chunk_count=count,
        )
        preview_rows.append(
            {
                "strategy": strategy,
                "status_code": status,
                "elapsed_sec": round(elapsed, 3),
                "chunk_count": count,
            }
        )
    return preview_rows


def kg_extract_path(document_id: str, kg_backend: str) -> str:
    params = {
        "replace_existing": "true",
        "extract_relations": "false",
        "extract_skills": "false",
    }
    if str(kg_backend or "").strip():
        params["extraction_backend"] = str(kg_backend).strip()
    return f"/api/v1/kg/documents/{document_id}/extract?{urlencode(params)}"


def run_kg_flow(
    api: LiveApi,
    steps: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    args: argparse.Namespace,
    dataset_id: str,
    document_id: str,
) -> None:
    status, body, elapsed = api.json(
        "POST",
        kg_extract_path(document_id, str(args.kg_backend or "")),
        payload={},
        timeout=args.timeout,
    )
    record_step(steps, "kg_extract", status, body, elapsed)
    summary["kg_extract_status"] = status
    summary["kg_extract_elapsed_sec"] = round(elapsed, 3)
    summary["kg_extract_body"] = body

    status, body, elapsed = api.json(
        "GET",
        f"/api/v1/kg/stats?dataset_id={dataset_id}",
        timeout=120,
    )
    record_step(steps, "kg_stats", status, body, elapsed)
    summary["kg_stats_status"] = status
    summary["kg_stats_elapsed_sec"] = round(elapsed, 3)
    summary["kg_stats"] = body

    kg_search_rows: list[dict[str, Any]] = []
    for question in effective_questions(list(args.kg_query or []), DEFAULT_KG_QUERIES):
        status, body, elapsed = api.json(
            "POST",
            "/api/v1/kg/search",
            payload={"query": question, "dataset_id": dataset_id},
            timeout=120,
        )
        result_payload = body.get("result") if isinstance(body, dict) else None
        result_payload = result_payload if isinstance(result_payload, dict) else {}
        clues = result_payload.get("clues")
        events = result_payload.get("events")
        clue_count = len(clues) if isinstance(clues, list) else 0
        event_count = len(events) if isinstance(events, list) else 0
        record_step(
            steps,
            "kg_search",
            status,
            body,
            elapsed,
            question=question,
            clue_count=clue_count,
            event_count=event_count,
            returned=list_count(body),
        )
        kg_search_rows.append(
            {
                "question": question,
                "status_code": status,
                "elapsed_sec": round(elapsed, 3),
                "clue_count": clue_count,
                "event_count": event_count,
            }
        )
    summary["kg_search_results"] = kg_search_rows
    if kg_search_rows:
        summary["kg_search_status"] = kg_search_rows[0]["status_code"]
        summary["kg_search_elapsed_sec"] = kg_search_rows[0]["elapsed_sec"]
        summary["kg_search_count"] = kg_search_rows[0]["clue_count"]


def chat_payload(question: str, dataset_id: str, *, use_graph: bool) -> dict[str, Any]:
    return {
        "message": question,
        "dataset_id": dataset_id,
        "stream": False,
        "rag_config": {
            "top_k": 6,
            "score_threshold": 0.0,
            "retrieval_mode": "hybrid",
            "use_graph": use_graph,
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
            "max_tokens": 700,
            "answer_mode": "extractive",
        },
    }


def answer_preview_and_citations(body: Any) -> tuple[str, int]:
    if not isinstance(body, dict):
        return "", 0
    answer = str(body.get("response") or body.get("answer") or body.get("message") or body.get("content") or "")
    return answer, len(body.get("citations") or [])


def run_chat_flow(
    api: LiveApi,
    steps: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    args: argparse.Namespace,
    dataset_id: str,
) -> None:
    chat_questions = effective_questions(
        list(args.chat_question or []),
        DEFAULT_CHAT_QUESTIONS,
    )
    chat_rows: list[dict[str, Any]] = []
    for question in chat_questions:
        for label, use_graph in (("chat_baseline", False), ("chat_graph", True)):
            status, body, elapsed = api.json(
                "POST",
                "/api/v1/chat",
                payload=chat_payload(question, dataset_id, use_graph=use_graph),
                timeout=args.timeout,
            )
            answer, citation_count = answer_preview_and_citations(body)
            record_step(
                steps,
                label,
                status,
                body,
                elapsed,
                question=question,
                citation_count=citation_count,
                answer_preview=answer[:300],
            )
            row = {
                "question": question,
                "mode": "graph" if use_graph else "baseline",
                "status_code": status,
                "elapsed_sec": round(elapsed, 3),
                "citation_count": citation_count,
                "answer_preview": answer[:500],
            }
            chat_rows.append(row)
            if len(chat_questions) == 1:
                summary[label] = {
                    "status_code": status,
                    "elapsed_sec": round(elapsed, 3),
                    "citation_count": citation_count,
                    "answer_preview": answer[:500],
                }
    summary["chat_results"] = chat_rows


def execute_chain(
    args: argparse.Namespace,
    *,
    api: LiveApi,
    steps: list[dict[str, Any]],
    summary: dict[str, Any],
    pdf_path: Path,
    run_id: str,
) -> None:
    parser_backend = str(args.parser_backend or "magicpdf")
    dataset_id = create_dataset(api, steps, parser_backend=parser_backend, run_id=run_id)
    summary["dataset_id"] = dataset_id

    document_id = upload_document(
        api,
        steps,
        dataset_id=dataset_id,
        parser_backend=parser_backend,
        pdf_path=pdf_path,
        timeout=args.timeout,
    )
    summary["document_id"] = document_id
    document_status, document_body = poll_document_until_complete(
        api,
        steps,
        document_id=document_id,
        timeout=args.timeout,
        poll_timeout=args.poll_timeout,
    )
    summary["document_status"] = document_status
    if document_status != "completed":
        raise RuntimeError(f"document did not complete: {snippet(document_body)}")
    summary["chunk_count"] = fetch_chunk_count(
        api,
        steps,
        document_id=document_id,
        timeout=args.timeout,
    )
    summary["parsed_chars"] = fetch_parsed_chars(
        api,
        steps,
        document_id=document_id,
        timeout=args.timeout,
    )
    summary["chunk_preview"] = run_chunk_previews(
        api,
        steps,
        chunk_strategies=str(args.chunk_strategies or ""),
        dataset_id=dataset_id,
        parser_backend=parser_backend,
        pdf_path=pdf_path,
        timeout=args.timeout,
    )

    if not args.skip_kg:
        run_kg_flow(
            api,
            steps,
            summary,
            args=args,
            dataset_id=dataset_id,
            document_id=document_id,
        )
    if not args.skip_chat:
        run_chat_flow(
            api,
            steps,
            summary,
            args=args,
            dataset_id=dataset_id,
        )

    summary["cleanup"] = perform_cleanup(
        api=api,
        steps=steps,
        dataset_id=dataset_id,
        document_id=document_id,
        cleanup_mode=str(args.cleanup_mode or "none"),
        delete_dataset_after=bool(args.delete_dataset_after),
        timeout=int(args.timeout),
    )


def write_report(artifact_dir: Path, summary: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    summary["steps"] = steps
    (artifact_dir / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: summary.get(key)
                for key in (
                    "ok",
                    "artifact_dir",
                    "dataset_id",
                    "document_id",
                    "chunk_count",
                    "kg_extract_status",
                    "kg_stats_status",
                    "kg_search_status",
                    "error",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    args = build_arg_parser().parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir, pdf_path, source = create_run_artifacts(args, run_id=run_id)

    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "source": source,
        "pdf_bytes": int(pdf_path.stat().st_size),
    }

    try:
        execute_chain(
            args,
            api=api,
            steps=steps,
            summary=summary,
            pdf_path=pdf_path,
            run_id=run_id,
        )
        summary["ok"] = True
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
        write_report(artifact_dir, summary, steps)
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
