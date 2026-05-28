#!/usr/bin/env python3
"""Remote KG scale guard smoke test.

Creates a bounded synthetic corpus on a live server, runs heuristic KG
extraction, and records extraction latency plus graph stats. Standard-library
only so it can run on the deployment host without extra packages.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import traceback
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


class Api:
    def __init__(self, base_url: str, tenant_id: str, account_id: str, user_id: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "X-Tenant-ID": tenant_id,
            "X-Account-ID": account_id,
            "X-User-ID": user_id,
        }

    def json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any, float]:
        headers = dict(self.headers)
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request(method, path, data, headers)

    def multipart(self, path: str, fields: dict[str, str], filename: str, content: str) -> tuple[int, Any, float]:
        boundary = f"----MimirQKgScale{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for key, value in fields.items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            parts.append(str(value).encode("utf-8"))
            parts.append(b"\r\n")
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: text/markdown; charset=utf-8\r\n\r\n"
            ).encode()
        )
        parts.append(content.encode("utf-8"))
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        headers = dict(self.headers)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self._request("POST", path, b"".join(parts), headers)

    def _request(self, method: str, path: str, data: bytes | None, headers: dict[str, str]) -> tuple[int, Any, float]:
        started = time.perf_counter()
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
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


def make_doc(index: int) -> str:
    plant = f"Plant-{index % 4 + 1}"
    system = ["Parser", "Chunker", "Retriever", "Graph"][index % 4]
    owner = ["Ingestion", "RAG", "Platform", "Governance"][index % 4]
    return (
        f"# KG Scale Incident {index:02d}\n\n"
        f"On 2026-05-{index % 20 + 1:02d}, {system} in {plant} reported a latency event. "
        f"The {owner} team linked the event to dataset batch Batch-{index % 5} and service Service-{index % 6}. "
        "MimirQ should extract only important entities and events instead of every sentence.\n\n"
        "## Decision\n\n"
        f"{owner} keeps RAG citation retrieval as the primary answer path. "
        f"KG records sparse relations between {system}, {plant}, Batch-{index % 5}, and Service-{index % 6}.\n\n"
        "## Action Items\n\n"
        "- Record request id and document id.\n"
        "- Keep extraction bounded by event budget.\n"
        "- Avoid generating dense graph edges for routine prose.\n"
    )


def body_snippet(body: Any, limit: int = 500) -> str:
    return json.dumps(body, ensure_ascii=False, default=str)[:limit]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[idx]


def run(args: argparse.Namespace) -> dict[str, Any]:
    api = Api(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    artifact_dir = Path(args.artifact_dir or f"artifacts/kg-scale-guard/remote-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    def write_progress(payload: dict[str, Any]) -> None:
        payload = {**payload, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        (artifact_dir / "progress.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    write_progress({"phase": "start", "doc_count": args.doc_count, "base_url": args.base_url})

    status, body, elapsed = api.json(
        "POST",
        "/api/v1/datasets/",
        {
            "name": f"KG Scale Guard {time.strftime('%Y%m%d-%H%M%S')}",
            "description": "Remote KG scale guard synthetic corpus.",
            "default_parser_backend": "auto",
            "default_chunk_strategy": "langchain_recursive",
            "pipeline": {
                "persist_parsed_content": True,
                "chunk_size": 900,
                "chunk_overlap": 80,
                "chunk_vector_enabled": False,
                "bm25_index_enabled": False,
                "kg_enabled": False,
            },
        },
    )
    if not (200 <= status < 300):
        raise RuntimeError(f"create dataset failed {status}: {body_snippet(body)}")
    dataset_id = str((body or {}).get("id") or (body or {}).get("dataset_id") or "")
    if not dataset_id:
        raise RuntimeError(f"dataset id missing: {body_snippet(body)}")
    write_progress({"phase": "dataset_created", "dataset_id": dataset_id, "doc_count": args.doc_count})

    uploads: list[dict[str, Any]] = []
    for index in range(args.doc_count):
        write_progress({"phase": "uploading", "dataset_id": dataset_id, "index": index, "uploaded": len(uploads)})
        filename = f"kg-scale-{index:02d}.md"
        fields = {
            "dataset_id": dataset_id,
            "parser_backend": "auto",
            "chunk_strategy": "langchain_recursive",
            "chunk_vector_enabled": "false",
            "bm25_index_enabled": "false",
            "kg_enabled": "false",
        }
        status, body, elapsed = api.multipart("/api/v1/documents/upload", fields, filename, make_doc(index))
        uploads.append(
            {
                "filename": filename,
                "status_code": status,
                "ok": 200 <= status < 300,
                "document_id": str((body or {}).get("id") or (body or {}).get("document_id") or ""),
                "elapsed_sec": round(elapsed, 3),
                "error": None if 200 <= status < 300 else body_snippet(body),
            }
        )
    write_progress({"phase": "uploads_done", "dataset_id": dataset_id, "uploads": uploads})

    documents: list[dict[str, Any]] = []
    for upload in uploads:
        if not upload["ok"]:
            continue
        write_progress(
            {
                "phase": "polling_documents",
                "dataset_id": dataset_id,
                "current": upload["filename"],
                "documents": documents,
            }
        )
        document_id = upload["document_id"]
        deadline = time.time() + args.poll_timeout
        detail: Any = None
        while time.time() < deadline:
            status, detail, elapsed = api.json("GET", f"/api/v1/documents/{document_id}")
            if not (200 <= status < 300):
                break
            state = str((detail or {}).get("status") or "").lower()
            if state in {"completed", "failed", "quarantined", "cancelled"}:
                break
            time.sleep(1)
        state = str((detail or {}).get("status") or "").lower() if isinstance(detail, dict) else ""
        documents.append(
            {
                "filename": upload["filename"],
                "document_id": document_id,
                "status": state,
                "ok": state == "completed",
            }
        )
    write_progress({"phase": "documents_done", "dataset_id": dataset_id, "documents": documents})

    extract_results: list[dict[str, Any]] = []
    params = urlencode(
        {
            "replace_existing": "true",
            "extract_relations": "false",
            "extract_skills": "false",
            "extraction_backend": "heuristic",
        }
    )
    for doc in documents:
        if not doc["ok"]:
            continue
        write_progress(
            {
                "phase": "extracting_kg",
                "dataset_id": dataset_id,
                "current": doc["filename"],
                "completed": len(extract_results),
                "documents": documents,
            }
        )
        status, body, elapsed = api.json("POST", f"/api/v1/kg/documents/{doc['document_id']}/extract?{params}")
        extract_results.append(
            {
                "filename": doc["filename"],
                "document_id": doc["document_id"],
                "status_code": status,
                "ok": 200 <= status < 300,
                "elapsed_sec": round(elapsed, 3),
                "response": body if isinstance(body, dict) else str(body)[:500],
                "error": None if 200 <= status < 300 else body_snippet(body),
            }
        )
    write_progress({"phase": "extract_done", "dataset_id": dataset_id, "extract_results": extract_results})

    write_progress({"phase": "kg_stats", "dataset_id": dataset_id, "extract_results": extract_results})
    stats_status, stats_body, stats_elapsed = api.json("GET", f"/api/v1/kg/stats?dataset_id={dataset_id}")
    write_progress({"phase": "kg_search", "dataset_id": dataset_id, "stats_status": stats_status})
    search_status, search_body, search_elapsed = api.json(
        "POST",
        "/api/v1/kg/search",
        {"query": "bounded KG event budget parser service", "dataset_id": dataset_id},
    )

    elapsed_values = [float(item["elapsed_sec"]) for item in extract_results if item["ok"]]
    avg_extract_sec = statistics.mean(elapsed_values) if elapsed_values else 0.0
    p95_extract_sec = percentile(elapsed_values, 0.95)
    max_extract_sec = max(elapsed_values or [0.0])

    summary = {
        "ok": (
            len(uploads) == args.doc_count
            and all(item["ok"] for item in uploads)
            and len(documents) == args.doc_count
            and all(item["ok"] for item in documents)
            and len(extract_results) == args.doc_count
            and all(item["ok"] for item in extract_results)
            and 200 <= stats_status < 300
            and 200 <= search_status < 300
            and avg_extract_sec <= args.max_avg_extract_sec
            and max_extract_sec <= args.max_doc_extract_sec
        ),
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "dataset_id": dataset_id,
        "doc_count": args.doc_count,
        "uploads": uploads,
        "documents": documents,
        "extract_results": extract_results,
        "avg_extract_sec": round(avg_extract_sec, 3),
        "p95_extract_sec": round(p95_extract_sec, 3),
        "max_extract_sec": round(max_extract_sec, 3),
        "max_avg_extract_sec": args.max_avg_extract_sec,
        "max_doc_extract_sec": args.max_doc_extract_sec,
        "kg_stats_status": stats_status,
        "kg_stats_elapsed_sec": round(stats_elapsed, 3),
        "kg_stats": stats_body,
        "kg_search_status": search_status,
        "kg_search_elapsed_sec": round(search_elapsed, 3),
        "kg_search_response": search_body,
    }
    (artifact_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Remote KG Scale Guard",
        "",
        f"- ok: `{summary['ok']}`",
        f"- dataset_id: `{dataset_id}`",
        f"- documents: `{sum(1 for item in documents if item['ok'])}/{args.doc_count}`",
        f"- extraction: `{sum(1 for item in extract_results if item['ok'])}/{args.doc_count}`",
        f"- avg_extract_sec: `{summary['avg_extract_sec']}`",
        f"- p95_extract_sec: `{summary['p95_extract_sec']}`",
        f"- max_extract_sec: `{summary['max_extract_sec']}`",
        f"- kg_stats_status: `{stats_status}`",
        f"- kg_search_status: `{search_status}`",
        "",
        "## Extraction Results",
    ]
    for item in extract_results:
        lines.append(f"- {item['filename']}: ok={item['ok']} status={item['status_code']} elapsed={item['elapsed_sec']}s")
    (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a remote KG scale guard smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--doc-count", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-timeout", type=int, default=180)
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--max-avg-extract-sec", type=float, default=15.0)
    parser.add_argument("--max-doc-extract-sec", type=float, default=25.0)
    args = parser.parse_args()
    if not args.artifact_dir:
        args.artifact_dir = f"artifacts/kg-scale-guard/remote-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        summary = run(args)
    except BaseException as exc:  # noqa: BLE001 - persist diagnostics for remote smoke runs.
        artifact_dir = Path(args.artifact_dir).resolve()
        fallback: dict[str, Any] = {
            "ok": False,
            "error": str(exc),
            "exception_type": exc.__class__.__name__,
            "traceback": traceback.format_exc(),
            "artifact_dir": str(artifact_dir),
        }
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "report.json").write_text(json.dumps(fallback, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(fallback, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                key: summary.get(key)
                for key in (
                    "ok",
                    "artifact_dir",
                    "dataset_id",
                    "doc_count",
                    "avg_extract_sec",
                    "p95_extract_sec",
                    "max_extract_sec",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
