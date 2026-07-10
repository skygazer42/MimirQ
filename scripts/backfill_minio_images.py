
import argparse
import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _strip_trailing_slashes(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _join_url(base: str, path: str) -> str:
    b = _strip_trailing_slashes(base)
    p = (path or "").strip()
    if not p:
        return b
    if not p.startswith("/"):
        p = f"/{p}"
    return f"{b}{p}"


def _chunks(items: list[str], n: int) -> Iterable[list[str]]:
    step = max(1, int(n or 1))
    for i in range(0, len(items), step):
        yield items[i : i + step]


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _doc_image_count(meta: dict[str, Any]) -> int:
    try:
        raw = meta.get("document_analytics_raw")
        if isinstance(raw, dict):
            return max(0, int(raw.get("image_count") or 0))
    except Exception:
        return 0
    return 0


def _doc_has_minio_images(meta: dict[str, Any]) -> bool:
    img_ids = _coerce_str_list(meta.get("img_ids"))
    return bool(img_ids)


@dataclass(frozen=True)
class HttpResult:
    status_code: int | None
    elapsed_ms: int
    data: Any | None
    error: str | None


def _request_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: Any | None = None,
    timeout_sec: float = 30.0,
) -> HttpResult:
    start = time.perf_counter()
    body: bytes | None = None
    hdrs = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")

    try:
        req = Request(url, method=method.upper(), headers=hdrs, data=body)
        with urlopen(req, timeout=float(timeout_sec)) as resp:
            raw = resp.read() or b""
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            content_type = (resp.headers.get("Content-Type") or "").lower()
            parsed: Any
            if "application/json" in content_type:
                parsed = json.loads(raw.decode("utf-8")) if raw else None
            else:
                parsed = raw.decode("utf-8", errors="replace") if raw else None
            return HttpResult(status_code=int(getattr(resp, "status", 0) or 0), elapsed_ms=elapsed_ms, data=parsed, error=None)
    except HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        raw = exc.read() if hasattr(exc, "read") else b""
        parsed: Any | None = None
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = raw.decode("utf-8", errors="replace")
        return HttpResult(status_code=int(getattr(exc, "code", 0) or 0) or None, elapsed_ms=elapsed_ms, data=parsed, error=f"HTTPError: {getattr(exc, 'code', 'unknown')}")
    except URLError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return HttpResult(status_code=None, elapsed_ms=elapsed_ms, data=None, error=f"URLError: {exc}")


def _build_auth_headers(*, auth_mode: str, tenant_id: str, user_id: str | None, token: str | None) -> dict[str, str]:
    mode = (auth_mode or "header").strip().lower()
    headers: dict[str, str] = {"Accept": "application/json", "X-Tenant-ID": str(tenant_id)}

    if mode == "header":
        if not user_id:
            raise ValueError("user_id_required_for_header_mode")
        headers["X-User-ID"] = str(user_id)
        return headers

    if mode == "jwt":
        if not token:
            raise ValueError("token_required_for_jwt_mode")
        tok = str(token).strip()
        headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
        return headers

    raise ValueError("invalid_auth_mode")


def _iter_dataset_document_ids(
    *,
    base_url: str,
    dataset_id: str,
    headers: dict[str, str],
    only_missing_img_ids: bool,
    require_image_count: bool,
    timeout_sec: float,
) -> list[str]:
    out: list[str] = []
    skip = 0
    limit = 200

    while True:
        url = _join_url(
            base_url,
            f"/api/v1/documents?skip={skip}&limit={limit}&lifecycle=active&dataset_id={dataset_id}",
        )
        res = _request_json(url, method="GET", headers=headers, timeout_sec=timeout_sec)
        if not res.status_code or res.status_code < 200 or res.status_code >= 300:
            raise RuntimeError(f"list_documents_failed: {res.status_code} {res.error or ''} {res.data!r}")

        data = res.data if isinstance(res.data, dict) else {}
        items = data.get("items")
        if not isinstance(items, list):
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("id") or "").strip()
            if not doc_id:
                continue
            meta = item.get("metadata")
            meta_dict = meta if isinstance(meta, dict) else {}

            if only_missing_img_ids and _doc_has_minio_images(meta_dict):
                continue
            if require_image_count and _doc_image_count(meta_dict) <= 0:
                continue
            out.append(doc_id)

        if len(items) < limit:
            break
        skip += limit

    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill MinIO img_id for historical documents by triggering document reprocess.\n\n"
            "Typical workflow:\n"
            "  1) Enable MinIO (MINIO_ENABLED=true)\n"
            "  2) Run this script to retry documents missing metadata.img_ids\n"
        )
    )
    parser.add_argument(
        "--base-url",
        default=_strip_trailing_slashes(os.getenv("BACKEND_BASE_URL") or "http://localhost:8000"),
        help="Backend base URL (default: env BACKEND_BASE_URL or http://localhost:8000)",
    )
    parser.add_argument("--dataset-id", required=True, help="Target dataset UUID")
    parser.add_argument(
        "--auth-mode",
        default=str(os.getenv("AUTH_MODE") or "header"),
        choices=["header", "jwt"],
        help="Auth mode: header (X-User-ID) or jwt (Authorization Bearer). Default: env AUTH_MODE or header",
    )
    parser.add_argument(
        "--tenant-id",
        default=str(os.getenv("NEXT_PUBLIC_TENANT_ID") or ""),
        help="Tenant UUID (default: env NEXT_PUBLIC_TENANT_ID)",
    )
    parser.add_argument(
        "--user-id",
        default=str(os.getenv("NEXT_PUBLIC_USER_ID") or ""),
        help="Header auth mode user id (default: env NEXT_PUBLIC_USER_ID)",
    )
    parser.add_argument(
        "--token",
        default=str(os.getenv("MIMIRQ_TOKEN") or ""),
        help="JWT auth mode access token (default: env MIMIRQ_TOKEN)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for /documents/batch/retry (max 200). Default: 200",
    )
    parser.add_argument("--force", action="store_true", help="Force reprocess even if already completed (recommended)")
    parser.add_argument(
        "--skip-if-unchanged",
        action="store_true",
        help="When used with --force, skip processing for unchanged docs (advanced)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Retry all documents in the dataset (default: only docs missing metadata.img_ids)",
    )
    parser.add_argument(
        "--require-image-count",
        action="store_true",
        help="Only retry docs whose metadata.document_analytics_raw.image_count > 0",
    )
    parser.add_argument("--dry-run", action="store_true", help="List candidate docs without retrying")
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("BACKFILL_TIMEOUT_SEC") or "30"),
        help="HTTP timeout per request (seconds). Default: 30",
    )
    args = parser.parse_args()

    base_url = _strip_trailing_slashes(str(args.base_url))
    dataset_id = str(args.dataset_id).strip()
    tenant_id = str(args.tenant_id).strip()
    if not tenant_id:
        raise SystemExit("ERROR: --tenant-id is required (or set NEXT_PUBLIC_TENANT_ID)")

    auth_mode = str(args.auth_mode).strip().lower()
    user_id = str(args.user_id).strip() or None
    token = str(args.token).strip() or None
    timeout_sec = float(args.timeout)

    headers = _build_auth_headers(auth_mode=auth_mode, tenant_id=tenant_id, user_id=user_id, token=token)

    only_missing_img_ids = not bool(args.all)

    batch_size = int(args.batch_size or 200)
    batch_size = max(1, min(200, batch_size))

    # Best-effort warning (does not block execution).
    ready = _request_json(_join_url(base_url, "/api/v1/health/ready"), method="GET", headers={"Accept": "application/json"}, timeout_sec=timeout_sec)
    if isinstance(ready.data, dict):
        minio_status = ready.data.get("minio")
        if isinstance(minio_status, dict):
            enabled = bool(minio_status.get("enabled"))
            status = str(minio_status.get("status") or "")
            if not enabled:
                print("[backfill] WARN: /health/ready reports MINIO disabled; backfill will not upload images")
            elif status and status != "connected":
                print(f"[backfill] WARN: /health/ready reports MINIO status={status}")

    print("[backfill] Listing documents...")
    doc_ids = _iter_dataset_document_ids(
        base_url=base_url,
        dataset_id=dataset_id,
        headers=headers,
        only_missing_img_ids=only_missing_img_ids,
        require_image_count=bool(args.require_image_count),
        timeout_sec=timeout_sec,
    )
    print(f"[backfill] Candidate documents: {len(doc_ids)}")
    if not doc_ids:
        return 0

    if bool(args.dry_run):
        print("[backfill] Dry run: no retries submitted.")
        for v in doc_ids[:10]:
            print(f"  - {v}")
        if len(doc_ids) > 10:
            print(f"  ... (+{len(doc_ids) - 10} more)")
        return 0

    payload_template = {
        "force": bool(args.force),
        "skip_if_unchanged": bool(args.skip_if_unchanged),
    }
    queued_total = 0
    skipped_total = 0
    for batch in _chunks(doc_ids, batch_size):
        url = _join_url(base_url, "/api/v1/documents/batch/retry")
        payload = dict(payload_template)
        payload["document_ids"] = batch
        res = _request_json(url, method="POST", headers=headers, payload=payload, timeout_sec=timeout_sec)
        if not res.status_code or res.status_code < 200 or res.status_code >= 300:
            raise RuntimeError(f"batch_retry_failed: {res.status_code} {res.error or ''} {res.data!r}")
        data = res.data if isinstance(res.data, dict) else {}
        queued_total += int(data.get("queued") or 0)
        skipped_total += int(data.get("skipped") or 0)
        print(f"[backfill] batch_retry: queued={data.get('queued')} skipped={data.get('skipped')} conflicts={len(data.get('conflicts') or [])}")

    print(f"[backfill] Done: queued={queued_total} skipped={skipped_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
