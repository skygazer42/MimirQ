#!/usr/bin/env python3
"""Live parser service matrix for deployment hosts.

The script generates a tiny text PDF, calls `/api/v1/pipeline/parse-preview`
for parser backends, and writes a compact report with latency, output size and
failure snippets. It intentionally uses only the standard library so it can run
on production-like hosts without installing test dependencies.
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
DEFAULT_BACKENDS = (
    "basic,deepdoc,docling,magicpdf,markitdown,"
    "etl4llm,marker,paddle_vl,olmocr,textin,deepseek_ocr,qianfan_ocr"
)


class LiveApi:
    def __init__(self, base_url: str, tenant_id: str, account_id: str, user_id: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.headers = {
            "X-Tenant-ID": tenant_id,
            "X-Account-ID": account_id,
            "X-User-ID": user_id,
        }

    def get_json(self, path: str) -> tuple[int, Any, float]:
        return self._request("GET", path, data=None, headers=dict(self.headers))

    def parse_preview(self, pdf_path: Path, backend: str) -> tuple[int, Any, float]:
        boundary = f"----MimirQParserMatrix{uuid.uuid4().hex}"
        payload = pdf_path.read_bytes()
        chunks: list[bytes] = []
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(b'Content-Disposition: form-data; name="parser_backend"\r\n\r\n')
        chunks.append(backend.encode("utf-8"))
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="file"; filename="{pdf_path.name}"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
        )
        chunks.append(payload)
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        headers = dict(self.headers)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self._request("POST", "/api/v1/pipeline/parse-preview", b"".join(chunks), headers)

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
            return status, text[:4000], elapsed


def _pdf_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_fixture_pdf(path: Path, *, pages: int = 2) -> None:
    """Write a small valid PDF with enough text for parser smoke tests."""
    page_texts = []
    for page in range(1, pages + 1):
        page_texts.append(
            [
                f"MimirQ parser matrix page {page}",
                "This fixture verifies non MinerU parser services.",
                "It includes retrieval, knowledge graph, OCR, tables, and governance keywords.",
                "Latency target fields: parser backend, dataset id, document id, request id.",
                "Simple table: Metric | Value | Owner.",
                "parser_success_rate | 0.99 | ingestion.",
                "kg_event_budget | 120 | graph.",
                "Contact demo@example.com is included for governance redaction checks.",
            ]
        )

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    font_obj_no = 3 + pages * 2
    for index, lines in enumerate(page_texts):
        page_obj_no = 3 + index * 2
        content_obj_no = page_obj_no + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_obj_no} 0 R >> >> "
                f"/Contents {content_obj_no} 0 R >>"
            ).encode()
        )
        escaped = "\n".join(f"({_pdf_escape(line)}) Tj T*" for line in lines)
        stream = f"BT /F1 12 Tf 72 740 Td 16 TL {escaped} ET".encode()
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for obj_no, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_no} 0 obj\n".encode())
        out.extend(payload)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    path.write_bytes(bytes(out))


def summarize_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"body_type": type(body).__name__, "body_preview": str(body)[:800]}
    markdown = str(body.get("markdown") or body.get("markdown_content") or body.get("content") or "")
    images = body.get("images")
    diagnostics = body.get("diagnostics") if isinstance(body.get("diagnostics"), dict) else {}
    pdf_quality = body.get("pdf_quality") if isinstance(body.get("pdf_quality"), dict) else {}
    return {
        "backend": body.get("backend"),
        "resolved_backend": body.get("resolved_backend"),
        "markdown_chars": len(markdown),
        "markdown_lines": markdown.count("\n") + (1 if markdown else 0),
        "images": len(images) if isinstance(images, list) else 0,
        "pdf_page_count": pdf_quality.get("page_count"),
        "pdf_score": pdf_quality.get("score"),
        "diagnostics_keys": sorted(str(k) for k in diagnostics.keys())[:20],
        "text_sample": markdown[:300],
    }


def classify_failure(status: int, body: Any, summary: dict[str, Any], min_markdown_chars: int) -> str:
    text = json.dumps(body, ensure_ascii=False, default=str) if not isinstance(body, str) else body
    lowered = text.lower()
    if status == 0:
        return "network_or_timeout"
    if status in {400, 404, 409, 422} and any(word in lowered for word in ("disabled", "not enabled", "missing", "configure")):
        return "unavailable_or_missing_config"
    if status >= 500:
        return "service_error"
    if not (200 <= status < 300):
        return "http_error"
    if int(summary.get("markdown_chars") or 0) < min_markdown_chars:
        return "low_output"
    return "ok"


def parser_messages(status_body: Any) -> dict[str, Any]:
    if not isinstance(status_body, dict):
        return {}
    parsers = status_body.get("parsers")
    return parsers if isinstance(parsers, dict) else {}


def run(args: argparse.Namespace) -> dict[str, Any]:
    artifact_dir = Path(args.artifact_dir or f"artifacts/parser-service-matrix/remote-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = artifact_dir / "parser-service-fixture.pdf"
    write_fixture_pdf(pdf_path, pages=args.pages)

    api = LiveApi(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    status_code, status_body, status_elapsed = api.get_json("/api/v1/settings/status")
    parser_status = parser_messages(status_body)
    (artifact_dir / "settings-status.json").write_text(
        json.dumps({"status_code": status_code, "elapsed_sec": round(status_elapsed, 3), "body": status_body}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    backends = [item.strip() for item in args.backends.split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    for backend in backends:
        status, body, elapsed = api.parse_preview(pdf_path, backend)
        summary = summarize_body(body)
        failure_class = classify_failure(status, body, summary, args.min_markdown_chars)
        ok = failure_class == "ok"
        status_entry = parser_status.get(backend) if isinstance(parser_status.get(backend), dict) else {}
        result = {
            "backend_requested": backend,
            "status_code": status,
            "ok": ok,
            "failure_class": failure_class,
            "elapsed_sec": round(elapsed, 3),
            "settings_enabled": status_entry.get("enabled"),
            "settings_available": status_entry.get("available"),
            "settings_message": status_entry.get("message"),
            **summary,
        }
        if not ok:
            result["error"] = json.dumps(body, ensure_ascii=False, default=str)[:1500]
        results.append(result)
        (artifact_dir / "progress.json").write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "ok": all(item["ok"] for item in results if item["backend_requested"] not in args.allowed_failures_set),
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "fixture": {"path": str(pdf_path), "bytes": pdf_path.stat().st_size, "pages": args.pages},
        "settings_status_code": status_code,
        "settings_elapsed_sec": round(status_elapsed, 3),
        "backends": backends,
        "allowed_failures": sorted(args.allowed_failures_set),
        "results": results,
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Remote Parser Service Matrix",
        "",
        f"- ok: `{report['ok']}`",
        f"- base_url: `{args.base_url}`",
        f"- fixture: `{pdf_path}` ({pdf_path.stat().st_size} bytes, {args.pages} pages)",
        "",
        "## Results",
    ]
    for item in results:
        lines.append(
            f"- {item['backend_requested']}: ok={item['ok']} class={item['failure_class']} "
            f"status={item['status_code']} elapsed={item['elapsed_sec']}s "
            f"chars={item.get('markdown_chars')} settings={item.get('settings_message')}"
        )
    (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a parser service matrix against a live MimirQ API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--backends", default=DEFAULT_BACKENDS)
    parser.add_argument("--allowed-failures", default="qianfan_ocr")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--min-markdown-chars", type=int, default=80)
    args = parser.parse_args()
    args.allowed_failures_set = {item.strip() for item in args.allowed_failures.split(",") if item.strip()}
    report = run(args)
    print(json.dumps({key: report.get(key) for key in ("ok", "artifact_dir", "fixture")}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
