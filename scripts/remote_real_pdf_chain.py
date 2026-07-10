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


class LiveApi:
    def __init__(self, base_url: str, tenant_id: str, account_id: str, user_id: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.headers = {
            "X-Tenant-ID": tenant_id,
            "X-Account-ID": account_id,
            "X-User-ID": user_id,
        }

    def json(self, method: str, path: str, *, payload: dict[str, Any] | None = None, timeout: int | None = None) -> tuple[int, Any, float]:
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

    def _request(self, method: str, path: str, *, data: bytes | None, headers: dict[str, str], timeout: int) -> tuple[int, Any, float]:
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
    mode = (cleanup_mode or "none").strip().lower() or "none"
    if mode not in {"none", "delete_document", "purge_dataset"}:
        mode = "none"
    summary: dict[str, Any] = {"mode": mode}
    if mode == "none":
        return summary

    if mode == "delete_document":
        status, body, elapsed = api.json("DELETE", f"/api/v1/documents/{document_id}", timeout=timeout)
        record_step(steps, "cleanup:delete_document", status, body, elapsed)
        summary["delete_document_status"] = int(status)
        if not ok_status(status) and int(status) != 204:
            raise RuntimeError(f"delete document failed: {snippet(body)}")
    elif mode == "purge_dataset":
        status, body, elapsed = api.json(
            "POST",
            f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000",
            payload={},
            timeout=timeout,
        )
        record_step(steps, "cleanup:purge_dataset", status, body, elapsed)
        summary["purge_status"] = int(status)
        summary["purge_deleted"] = int((body or {}).get("deleted") or 0) if isinstance(body, dict) else 0
        if not ok_status(status):
            raise RuntimeError(f"purge dataset failed: {snippet(body)}")

    status, body, elapsed = api.json(
        "GET",
        f"/api/v1/datasets/{dataset_id}/documents/export?export_format=json&limit=10",
        timeout=min(int(timeout), 120),
    )
    remaining = list_count(body)
    record_step(steps, "cleanup:dataset_documents_export", status, body, elapsed, remaining_documents=remaining)
    summary["post_cleanup_document_count"] = int(remaining)
    if not ok_status(status):
        raise RuntimeError(f"dataset documents export failed: {snippet(body)}")
    if remaining > 0:
        raise RuntimeError(f"documents remain after cleanup: {remaining}")

    status, body, elapsed = api.json("GET", f"/api/v1/kg/stats?dataset_id={dataset_id}", timeout=min(int(timeout), 120))
    record_step(steps, "cleanup:kg_stats", status, body, elapsed)
    summary["post_cleanup_kg_stats"] = body
    if not ok_status(status):
        raise RuntimeError(f"kg stats after cleanup failed: {snippet(body)}")
    if isinstance(body, dict) and any(int(body.get(key) or 0) > 0 for key in ("events", "entities", "links")):
        raise RuntimeError(f"kg artifacts remain after cleanup: {snippet(body)}")

    if bool(delete_dataset_after):
        status, body, elapsed = api.json("DELETE", f"/api/v1/datasets/{dataset_id}", timeout=timeout)
        record_step(steps, "cleanup:delete_dataset", status, body, elapsed)
        summary["delete_dataset_status"] = int(status)
        if not ok_status(status) and int(status) != 204:
            raise RuntimeError(f"delete dataset failed: {snippet(body)}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real-PDF parse -> chunk -> KG -> chat chain against a live MimirQ API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--pdf-url", default="")
    parser.add_argument("--pdf-path", default="")
    parser.add_argument("--filename", default="large-paper.pdf")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--parser-backend", default="magicpdf")
    parser.add_argument("--chunk-strategies", default="langchain_recursive,parent_child,semantic_sentence,markdown_hierarchy")
    parser.add_argument("--kg-backend", default="")
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--download-timeout", type=int, default=300)
    parser.add_argument("--poll-timeout", type=int, default=7200)
    parser.add_argument("--skip-kg", action="store_true")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--kg-query", action="append", default=[], help="Repeatable KG search query override")
    parser.add_argument("--chat-question", action="append", default=[], help="Repeatable chat question override")
    parser.add_argument("--cleanup-mode", default="none")
    parser.add_argument("--delete-dataset-after", action="store_true")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/real-pdf-chain/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(args.pdf_path).resolve() if args.pdf_path else artifact_dir / args.filename
    source: dict[str, Any] = {"path": str(pdf_path)}
    if args.pdf_url:
        source = download(args.pdf_url, pdf_path, timeout=int(args.download_timeout))
    elif not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))

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
        status, body, elapsed = api.json("POST", "/api/v1/datasets/", payload={
            "name": f"Real PDF Chain {run_id}",
            "description": "Large real PDF parse/chunk/kg/rag verification",
            "default_parser_backend": str(args.parser_backend or "magicpdf"),
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
        })
        record_step(steps, "create_dataset", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"create_dataset failed: {snippet(body)}")
        dataset_id = str((body or {}).get("id") or (body or {}).get("dataset_id") or "")
        if not dataset_id:
            raise RuntimeError(f"create_dataset response missing id: {snippet(body)}")
        summary["dataset_id"] = dataset_id

        fields = {
            "dataset_id": dataset_id,
            "parser_backend": str(args.parser_backend or "magicpdf"),
            "chunk_strategy": "langchain_recursive",
            "governance_enabled": "true",
            "chunk_vector_enabled": "true",
            "bm25_index_enabled": "true",
            "kg_enabled": "false",
            "event_vector_enabled": "false",
            "entity_vector_enabled": "false",
        }
        status, body, elapsed = api.multipart("POST", "/api/v1/documents/upload", fields=fields, file_path=pdf_path, timeout=args.timeout)
        record_step(steps, "upload", status, body, elapsed)
        if not ok_status(status):
            raise RuntimeError(f"upload failed: {snippet(body)}")
        document_id = str((body or {}).get("id") or (body or {}).get("document_id") or "")
        if not document_id:
            raise RuntimeError(f"upload response missing document_id: {snippet(body)}")
        summary["document_id"] = document_id

        deadline = time.time() + int(args.poll_timeout)
        last_body: Any = None
        while time.time() < deadline:
            status, body, elapsed = api.json("GET", f"/api/v1/documents/{document_id}", timeout=args.timeout)
            last_body = body
            record_step(steps, "poll_document", status, body, elapsed, doc_status=str((body or {}).get("status") or ""))
            if not ok_status(status):
                raise RuntimeError(f"document poll failed: {snippet(body)}")
            doc_status = str((body or {}).get("status") or "").lower()
            if doc_status in {"completed", "failed", "quarantined", "cancelled"}:
                break
            time.sleep(5)
        final_status = str((last_body or {}).get("status") or "").lower()
        summary["document_status"] = final_status
        if final_status != "completed":
            raise RuntimeError(f"document did not complete: {snippet(last_body)}")

        status, body, elapsed = api.json(
            "GET",
            f"/api/v1/documents/{document_id}/chunks?limit={DOCUMENT_CHUNK_LIST_LIMIT}",
            timeout=args.timeout,
        )
        record_step(steps, "chunks", status, body, elapsed, chunk_count=list_count(body))
        if not ok_status(status):
            raise RuntimeError(f"chunks failed: {snippet(body)}")
        summary["chunk_count"] = list_count(body)

        status, body, elapsed = api.json("GET", f"/api/v1/documents/{document_id}/parsed-content?max_chars=50000", timeout=args.timeout)
        parsed_text = parsed_text_from_response(body)
        record_step(steps, "parsed_content", status, body, elapsed, parsed_chars=len(parsed_text))
        summary["parsed_chars"] = len(parsed_text)

        preview_rows: list[dict[str, Any]] = []
        for strategy in [item.strip() for item in str(args.chunk_strategies or "").split(",") if item.strip()]:
            preview_fields = {
                "dataset_id": dataset_id,
                "parser_backend": str(args.parser_backend or "magicpdf"),
                "chunk_strategy": strategy,
                "chunk_size": "1600",
                "chunk_overlap": "160",
                "include_original_text": "false",
                "include_chunks": "true",
                "max_chunks": "120",
            }
            status, body, elapsed = api.multipart("POST", "/api/v1/documents/chunk-preview", fields=preview_fields, file_path=pdf_path, timeout=args.timeout)
            count = list_count(body)
            record_step(steps, f"chunk_preview:{strategy}", status, body, elapsed, chunk_count=count)
            preview_rows.append({"strategy": strategy, "status_code": status, "elapsed_sec": round(elapsed, 3), "chunk_count": count})
        summary["chunk_preview"] = preview_rows

        kg_queries = effective_questions(list(args.kg_query or []), DEFAULT_KG_QUERIES)
        chat_questions = effective_questions(list(args.chat_question or []), DEFAULT_CHAT_QUESTIONS)

        if not args.skip_kg:
            params = {
                "replace_existing": "true",
                "extract_relations": "false",
                "extract_skills": "false",
            }
            if str(args.kg_backend or "").strip():
                params["extraction_backend"] = str(args.kg_backend).strip()
            status, body, elapsed = api.json("POST", f"/api/v1/kg/documents/{document_id}/extract?{urlencode(params)}", payload={}, timeout=args.timeout)
            record_step(steps, "kg_extract", status, body, elapsed)
            summary["kg_extract_status"] = status
            summary["kg_extract_elapsed_sec"] = round(elapsed, 3)
            summary["kg_extract_body"] = body

            status, body, elapsed = api.json("GET", f"/api/v1/kg/stats?dataset_id={dataset_id}", timeout=120)
            record_step(steps, "kg_stats", status, body, elapsed)
            summary["kg_stats_status"] = status
            summary["kg_stats_elapsed_sec"] = round(elapsed, 3)
            summary["kg_stats"] = body

            kg_search_rows: list[dict[str, Any]] = []
            for question in kg_queries:
                status, body, elapsed = api.json(
                    "POST",
                    "/api/v1/kg/search",
                    payload={"query": question, "dataset_id": dataset_id},
                    timeout=120,
                )
                result_payload = body.get("result") if isinstance(body, dict) and isinstance(body.get("result"), dict) else {}
                clues = result_payload.get("clues") if isinstance(result_payload, dict) else None
                events = result_payload.get("events") if isinstance(result_payload, dict) else None
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

        if not args.skip_chat:
            chat_rows: list[dict[str, Any]] = []
            for question in chat_questions:
                for label, use_graph in (("chat_baseline", False), ("chat_graph", True)):
                    payload = {
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
                    status, body, elapsed = api.json("POST", "/api/v1/chat", payload=payload, timeout=args.timeout)
                    answer = ""
                    citation_count = 0
                    if isinstance(body, dict):
                        answer = str(body.get("response") or body.get("answer") or body.get("message") or body.get("content") or "")
                        citation_count = len(body.get("citations") or [])
                    record_step(steps, label, status, body, elapsed, question=question, citation_count=citation_count, answer_preview=answer[:300])
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

        cleanup_summary = perform_cleanup(
            api=api,
            steps=steps,
            dataset_id=dataset_id,
            document_id=document_id,
            cleanup_mode=str(args.cleanup_mode or "none"),
            delete_dataset_after=bool(args.delete_dataset_after),
            timeout=int(args.timeout),
        )
        if cleanup_summary:
            summary["cleanup"] = cleanup_summary

        summary["ok"] = True
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
        summary["steps"] = steps
        (artifact_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
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
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
