
import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# Ensure repo root is on sys.path so `import app` works when invoked as:
#   python scripts/incident_bundle.py ...
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.incident_bundle_service import write_incident_bundle_zip  # noqa: E402


def _env(key: str, default: str = "") -> str:
    return str(os.getenv(key, default) or default)


def _json_or_text(resp: httpx.Response) -> Any:
    try:
        return resp.json() if resp.content else {}
    except Exception:
        return {"_error": "non_json_response", "text": (resp.text or "")[:2000]}


def _fetch_json(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    try:
        resp = client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}

    payload = _json_or_text(resp)
    return {
        "ok": resp.status_code == 200,
        "url": url,
        "status_code": int(resp.status_code),
        "body": payload,
    }


def _pick_body(result: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(result, dict) or not result:
        return None
    body = result.get("body")
    return body if isinstance(body, dict) else {"_raw": body}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download a PII-safe incident bundle zip for a request_id.")
    parser.add_argument("--base-url", default="", help="Backend base URL (default: NEXT_PUBLIC_API_URL or http://localhost:8000)")
    parser.add_argument("--tenant-id", default="", help="Tenant UUID (default: NEXT_PUBLIC_TENANT_ID or all-zero)")
    parser.add_argument("--token", default="", help="Bearer token for admin-only endpoints (optional)")
    parser.add_argument("--request-id", required=True, help="X-Request-ID to fetch incident artifacts for")
    parser.add_argument("--window-minutes", type=int, default=24 * 60, help="Trace bundle window in minutes (default: 1440)")
    parser.add_argument("--max-bytes", type=int, default=5_000_000, help="Max bytes to read from metrics tail (default: 5MB)")
    parser.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout (seconds)")
    parser.add_argument("--out", default="", help="Output zip path (default: runs/incident-<request_id>-<ts>.zip)")
    args = parser.parse_args(argv)

    base_url = (args.base_url or _env("NEXT_PUBLIC_API_URL", "http://localhost:8000")).rstrip("/")
    tenant_id = args.tenant_id or _env("NEXT_PUBLIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")
    token = (args.token or "").strip()
    request_id = str(args.request_id or "").strip()

    if not request_id:
        raise SystemExit("--request-id is required")

    out_path = args.out.strip()
    if not out_path:
        ts = int(time.time())
        out_path = str(Path("runs") / f"incident-{request_id}-{ts}.zip")
    out_file = Path(out_path)

    headers: dict[str, str] = {}
    if tenant_id:
        headers["X-Tenant-ID"] = str(tenant_id)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Do not inherit proxy env vars (common in sandboxes/CI and can break local calls).
    with httpx.Client(timeout=float(args.timeout_sec), trust_env=False) as client:
        meta = _fetch_json(client, url=f"{base_url}/api/v1/meta", headers=headers)
        ready = _fetch_json(client, url=f"{base_url}/api/v1/health/ready", headers=headers)
        config = _fetch_json(client, url=f"{base_url}/api/v1/observability/config/snapshot", headers=headers)
        access_graph_summary = _fetch_json(client, url=f"{base_url}/api/v1/audit/access-graph/summary", headers=headers)
        periodic_job_freshness = _fetch_json(
            client, url=f"{base_url}/api/v1/observability/periodic-jobs/freshness", headers=headers
        )
        trace = _fetch_json(
            client,
            url=(
                f"{base_url}/api/v1/observability/rag-metrics/trace-bundle"
                f"?request_id={request_id}&window_minutes={int(args.window_minutes)}&max_bytes={int(args.max_bytes)}"
            ),
            headers=headers,
        )

    # Store the response bodies (including error payloads) for offline debugging.
    write_incident_bundle_zip(
        out_path=out_file,
        request_id=request_id,
        base_url=base_url,
        tenant_id=str(tenant_id) if tenant_id else None,
        meta=_pick_body(meta),
        health_ready=_pick_body(ready),
        config_snapshot=_pick_body(config),
        trace_bundle=_pick_body(trace),
        access_graph_summary=_pick_body(access_graph_summary),
        periodic_job_freshness=_pick_body(periodic_job_freshness),
    )

    print(str(out_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
