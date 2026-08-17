#!/usr/bin/env python3
"""Remote large-PDF parser performance smoke test.

Downloads or reads one PDF, calls the live `/api/v1/pipeline/parse-preview`
endpoint for selected parser backends, and records latency plus output-size
signals. Standard-library only so it can run on a deployment host without
installing benchmark dependencies.
"""

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

    def parse_preview(self, pdf_path: Path, backend: str) -> tuple[int, Any, float]:
        boundary = f"----MimirQLargePdf{uuid.uuid4().hex}"
        payload = pdf_path.read_bytes()
        parts: list[bytes] = []
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(b'Content-Disposition: form-data; name="parser_backend"\r\n\r\n')
        parts.append(backend.encode("utf-8"))
        parts.append(b"\r\n")
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            (
                f'Content-Disposition: form-data; name="file"; filename="{pdf_path.name}"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
        )
        parts.append(payload)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        headers = dict(self.headers)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self._request("POST", "/api/v1/pipeline/parse-preview", b"".join(parts), headers)

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
            return status, text[:2000], elapsed


def download(url: str, target: Path, timeout: int) -> dict[str, Any]:
    if target.exists() and target.stat().st_size > 0:
        return {"url": url, "path": str(target), "bytes": target.stat().st_size, "cached": True}
    request = Request(url, headers={"User-Agent": "MimirQ remote parser benchmark"})
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


def summarize_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"body_type": type(body).__name__, "body_preview": str(body)[:500]}
    markdown = str(body.get("markdown") or "")
    pdf_quality = body.get("pdf_quality") if isinstance(body.get("pdf_quality"), dict) else {}
    return {
        "backend": body.get("backend"),
        "markdown_chars": len(markdown),
        "markdown_lines": markdown.count("\n") + (1 if markdown else 0),
        "images": len(body.get("images") or []) if isinstance(body.get("images"), list) else 0,
        "pdf_page_count": pdf_quality.get("page_count"),
        "pdf_score": pdf_quality.get("score"),
        "is_scanned": pdf_quality.get("is_scanned"),
        "text_sample": markdown[:400],
    }


def _normalize_backend(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def classify_result(status: int, summary: dict[str, Any], requested_backend: str, min_markdown_chars: int) -> str:
    if status == 0:
        return "network_or_timeout"
    if not (200 <= status < 300):
        return "http_error"
    if int(summary.get("markdown_chars") or 0) < min_markdown_chars:
        return "low_output"

    requested = _normalize_backend(requested_backend)
    resolved = _normalize_backend(summary.get("backend"))
    if requested and requested != "auto" and resolved and requested != resolved:
        return f"resolved_backend_mismatch:{resolved}"
    return "ok"


def run(args: argparse.Namespace) -> dict[str, Any]:
    artifact_dir = Path(
        args.artifact_dir or f"artifacts/pdf-performance/remote-{time.strftime('%Y%m%d-%H%M%S')}"
    ).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(args.pdf_path).resolve() if args.pdf_path else artifact_dir / args.filename
    source: dict[str, Any] = {"path": str(pdf_path)}
    if args.pdf_url:
        source = download(args.pdf_url, pdf_path, timeout=args.download_timeout)
    elif not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))

    api = Api(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    backends = [item.strip() for item in args.backends.split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    for backend in backends:
        status, body, elapsed = api.parse_preview(pdf_path, backend)
        summary = summarize_body(body)
        failure_class = classify_result(status, summary, backend, args.min_markdown_chars)
        ok = failure_class == "ok"
        result = {
            "backend_requested": backend,
            "status_code": status,
            "ok": ok,
            "failure_class": failure_class,
            "elapsed_sec": round(elapsed, 3),
            **summary,
        }
        if not ok:
            result["error"] = json.dumps(body, ensure_ascii=False, default=str)[:1000]
        results.append(result)
        (artifact_dir / "progress.json").write_text(
            json.dumps({"source": source, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    report = {
        "ok": all(item["ok"] for item in results),
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "source": source,
        "pdf_bytes": pdf_path.stat().st_size,
        "backends": backends,
        "results": results,
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Remote Large PDF Parser Performance",
        "",
        f"- ok: `{report['ok']}`",
        f"- source: `{source.get('url') or source.get('path')}`",
        f"- pdf_bytes: `{report['pdf_bytes']}`",
        "",
        "## Results",
    ]
    for item in results:
        lines.append(
            f"- {item['backend_requested']}: ok={item['ok']} status={item['status_code']} "
            f"class={item.get('failure_class')} resolved={item.get('backend')} "
            f"elapsed={item['elapsed_sec']}s chars={item.get('markdown_chars')} "
            f"pages={item.get('pdf_page_count')} images={item.get('images')}"
        )
    (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a large-PDF parser benchmark against a remote API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--pdf-url", default="")
    parser.add_argument("--pdf-path", default="")
    parser.add_argument("--filename", default="large-paper.pdf")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--backends", default="basic,markitdown,docling,mineru,magicpdf")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--download-timeout", type=int, default=300)
    parser.add_argument("--min-markdown-chars", type=int, default=5000)
    args = parser.parse_args()
    report = run(args)
    print(
        json.dumps(
            {key: report.get(key) for key in ("ok", "artifact_dir", "source", "pdf_bytes")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
