#!/usr/bin/env python3
"""Remote chunking and governance matrix smoke test.

Runs against a live MimirQ API and writes a reproducible report. The script is
standard-library only so it can run on production hosts and slim containers.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
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
        boundary = f"----MimirQMatrix{uuid.uuid4().hex}"
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
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
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
        req = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = int(resp.status)
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


def count_chunks(body: Any) -> int:
    if isinstance(body, dict):
        for key in ("chunks", "items", "preview_chunks", "paragraphs", "sentences"):
            value = body.get(key)
            if isinstance(value, list):
                return len(value)
        value = body.get("chunk_count")
        if isinstance(value, int):
            return value
    if isinstance(body, list):
        return len(body)
    return 0


def text_len(body: Any) -> int:
    if isinstance(body, dict):
        for key in ("markdown", "markdown_content", "content", "text"):
            value = body.get(key)
            if isinstance(value, str):
                return len(value)
    return 0


CHUNK_CASES: list[dict[str, str]] = [
    {
        "strategy": "langchain_recursive",
        "filename": "plain.md",
        "content": "# Overview\n\nMimirQ validates parser, chunking, governance, KG and RAG.\n\n## Details\n\nLatency and citation quality are recorded.",
    },
    {
        "strategy": "markdown_hierarchy",
        "filename": "hierarchy.md",
        "content": "# Root\n\nAlpha paragraph.\n\n## Section A\n\nSentence one. Sentence two.\n\n### Section A.1\n\nNested detail.",
    },
    {
        "strategy": "semantic_sentence",
        "filename": "semantic.txt",
        "content": "MimirQ ingests documents. It normalizes text. It creates chunks. It retrieves citations. It answers with evidence.",
    },
    {
        "strategy": "parent_child",
        "filename": "parent-child.md",
        "content": "# Parent\n\nThis parent section has enough text for child windows. It includes multiple sentences about parser workers, vector indexing, and governance.",
    },
    {
        "strategy": "csv_rows",
        "filename": "metrics.csv",
        "content": "metric,value,owner\nlatency_p95_ms,720,platform\nretrieval_mrr,0.74,rag\nkg_event_budget,120,graph\n",
    },
    {
        "strategy": "markdown_table",
        "filename": "table.md",
        "content": "| Metric | Value |\n| --- | --- |\n| parser_success_rate | 0.99 |\n| retrieval_mrr | 0.74 |\n",
    },
    {
        "strategy": "qa_markdown",
        "filename": "faq.md",
        "content": "### Q: What is KG used for?\nA: KG supports RAG retrieval with sparse relationships.\n\n### Q: What remains primary?\nA: Citation-backed RAG evidence.",
    },
    {
        "strategy": "meeting_minutes",
        "filename": "meeting.md",
        "content": "# Meeting Notes\n\n## Agenda\nReview parser rollout.\n\n## Decisions\nUse server-side smoke tests.\n\n## Action Items\n- Record artifacts.",
    },
    {
        "strategy": "timeline_events",
        "filename": "timeline.md",
        "content": "2026-05-22 Parser matrix passed on remote server.\n2026-05-22 RAG retrieval returned citations.\n2026-05-22 KG extraction stayed bounded.",
    },
    {
        "strategy": "api_reference",
        "filename": "api.md",
        "content": "GET /api/v1/health\nReturns dependency health.\n\nPOST /api/v1/rag/retrieve-preview\nReturns citations without answer generation.",
    },
    {
        "strategy": "jsonl_records",
        "filename": "records.jsonl",
        "content": "{\"event\":\"parse\",\"ok\":true}\n{\"event\":\"retrieve\",\"citations\":4}\n",
    },
    {
        "strategy": "yaml_manifest",
        "filename": "manifest.yaml",
        "content": "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: mimirq-config\n---\napiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: mimirq-api\n",
    },
    {
        "strategy": "dockerfile",
        "filename": "Dockerfile.txt",
        "content": "FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\nCMD [\"python\", \"-m\", \"uvicorn\", \"app.main:app\"]\n",
    },
    {
        "strategy": "sql_schema",
        "filename": "schema.sql",
        "content": "CREATE TABLE documents (id uuid primary key, filename text);\nCREATE INDEX idx_documents_filename ON documents(filename);\n",
    },
    {
        "strategy": "stacktrace",
        "filename": "trace.txt",
        "content": "Traceback (most recent call last):\n  File \"app.py\", line 1, in <module>\nRuntimeError: parser timeout\n",
    },
]


GOVERNANCE_CASES: list[dict[str, Any]] = [
    {
        "name": "pii_mask",
        "payload": {
            "markdown": "Contact alice@example.com or call 13800138000 for parser support.",
            "pii_anonymize": True,
            "pii_mode": "mask",
            "pii_mask": "[PII]",
            "include_diff": True,
        },
        "expect_changed": True,
        "expect_key": "pii_hits",
    },
    {
        "name": "secret_mask",
        "payload": {
            "markdown": "Bearer sk-1234567890abcdef1234567890abcdef should never be stored.",
            "secrets_redact": True,
            "secrets_mode": "mask",
            "secrets_mask": "[SECRET]",
            "include_diff": True,
        },
        "expect_changed": True,
        "expect_key": "secrets_hits",
    },
    {
        "name": "url_normalize",
        "payload": {
            "markdown": "Visit https://example.com/path?utm_source=ad&x=1&gclid=abc for docs.",
            "normalize_urls": True,
            "normalize_urls_strip_tracking": True,
            "include_diff": True,
        },
        "expect_changed": True,
        "expect_key": "urls_changed",
    },
    {
        "name": "duplicate_drop",
        "payload": {
            "markdown": "Footer repeated line\n\nUseful paragraph.\n\nFooter repeated line\n\nFooter repeated line\n",
            "drop_duplicate_paragraphs": True,
            "drop_duplicate_paragraphs_min_occurrences": 2,
            "drop_duplicate_paragraphs_min_chars": 10,
            "include_diff": True,
        },
        "expect_changed": True,
        "expect_smaller": True,
        "expect_key": "output_chars",
    },
    {
        "name": "html_table_normalize",
        "payload": {
            "markdown": "<html><body><h1>Table</h1><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></body></html>",
            "input_format": "html",
            "normalize_tables": True,
            "include_diff": True,
        },
        "expect_changed": True,
        "expect_key": "output_chars",
    },
    {
        "name": "low_density_drop",
        "payload": {
            "markdown": "!!!!!\n@@@@@\n#####\n",
            "drop_low_density": True,
            "drop_low_density_threshold": 0.5,
            "include_diff": True,
        },
        "expect_dropped": True,
        "expect_key": "drop_reason",
    },
]


def run(args: argparse.Namespace) -> dict[str, Any]:
    api = Api(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    artifact_dir = Path(args.artifact_dir or f"artifacts/chunk-governance-matrix/remote-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dataset_id = args.dataset_id
    if not dataset_id:
        status, body, elapsed = api.json(
            "POST",
            "/api/v1/datasets/",
            {
                "name": f"Chunk Governance Matrix {time.strftime('%Y%m%d-%H%M%S')}",
                "description": "Remote chunk and governance matrix smoke dataset.",
                "default_parser_backend": "auto",
                "default_chunk_strategy": "langchain_recursive",
            },
        )
        if not (200 <= status < 300):
            raise RuntimeError(f"create dataset failed {status}: {body}")
        dataset_id = str((body or {}).get("id") or (body or {}).get("dataset_id") or "")
        if not dataset_id:
            raise RuntimeError(f"dataset id missing from response: {body}")

    chunk_results: list[dict[str, Any]] = []
    for case in CHUNK_CASES:
        fields = {
            "dataset_id": dataset_id,
            "parser_backend": "auto",
            "chunk_strategy": case["strategy"],
            "chunk_size": "600",
            "chunk_overlap": "80",
            "include_original_text": "false",
            "include_chunks": "true",
            "max_chunks": "100",
        }
        status, body, elapsed = api.multipart("/api/v1/documents/chunk-preview", fields, case["filename"], case["content"])
        chunk_results.append(
            {
                "strategy": case["strategy"],
                "filename": case["filename"],
                "status_code": status,
                "ok": 200 <= status < 300 and count_chunks(body) > 0,
                "chunks": count_chunks(body),
                "elapsed_sec": round(elapsed, 3),
                "error": None if 200 <= status < 300 else json.dumps(body, ensure_ascii=False)[:500],
            }
        )

    governance_results: list[dict[str, Any]] = []
    for case in GOVERNANCE_CASES:
        status, body, elapsed = api.json("POST", "/api/v1/pipeline/clean-preview", case["payload"])
        ok_status = 200 <= status < 300
        changed = bool((body or {}).get("changed")) if isinstance(body, dict) else False
        dropped = bool((body or {}).get("dropped")) if isinstance(body, dict) else False
        input_chars = int((body or {}).get("input_chars") or 0) if isinstance(body, dict) else 0
        output_chars = text_len(body)
        expect_changed = bool(case.get("expect_changed"))
        expect_dropped = bool(case.get("expect_dropped"))
        expect_smaller = bool(case.get("expect_smaller"))
        expect_key = str(case.get("expect_key") or "")
        key_value = (body or {}).get(expect_key) if isinstance(body, dict) else None
        ok = ok_status and ((not expect_changed) or changed) and ((not expect_dropped) or dropped)
        if expect_smaller:
            ok = ok and output_chars < input_chars
        if expect_key:
            ok = ok and key_value not in (None, {}, 0, "")
        governance_results.append(
            {
                "name": case["name"],
                "status_code": status,
                "ok": ok,
                "changed": changed,
                "dropped": dropped,
                "expect_key": expect_key,
                "expect_value": key_value,
                "input_chars": input_chars,
                "output_chars": output_chars,
                "elapsed_sec": round(elapsed, 3),
                "error": None if ok_status else json.dumps(body, ensure_ascii=False)[:500],
            }
        )

    summary = {
        "ok": all(item["ok"] for item in chunk_results) and all(item["ok"] for item in governance_results),
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "dataset_id": dataset_id,
        "chunk_results": chunk_results,
        "governance_results": governance_results,
    }
    (artifact_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Remote Chunk Governance Matrix",
        "",
        f"- ok: `{summary['ok']}`",
        f"- dataset_id: `{dataset_id}`",
        f"- chunk cases: `{sum(1 for item in chunk_results if item['ok'])}/{len(chunk_results)}`",
        f"- governance cases: `{sum(1 for item in governance_results if item['ok'])}/{len(governance_results)}`",
        "",
        "## Chunk Results",
    ]
    for item in chunk_results:
        lines.append(
            f"- {item['strategy']}: ok={item['ok']} status={item['status_code']} chunks={item['chunks']} elapsed={item['elapsed_sec']}s"
        )
    lines.append("")
    lines.append("## Governance Results")
    for item in governance_results:
        lines.append(
            f"- {item['name']}: ok={item['ok']} status={item['status_code']} changed={item['changed']} "
            f"dropped={item['dropped']} elapsed={item['elapsed_sec']}s"
        )
    (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run remote chunking and governance matrix smoke tests.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--dataset-id", default="")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps({k: summary[k] for k in ("ok", "artifact_dir", "dataset_id")}, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
