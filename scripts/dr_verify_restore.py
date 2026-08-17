#!/usr/bin/env python3
"""
DR restore verification runner (ops automation).

This script is intended to be used right after a restore in a DR/staging environment.
It produces a single JSON report and exits non-zero on failures.

Checks (bounded, PII-safe):
1) /api/v1/health/ready
2) End-to-end smoke test (ingest + chat) via scripts/smoke_test.py
3) Index audit for the smoke dataset (admin-only endpoint)

Notes:
- Requires admin credentials (token or user-id) to hit observability endpoints.
- Safe-by-default: does not print tokens; relies on smoke_test redaction.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_base_urls(raw_base_url: str) -> tuple[str, str]:
    """
    Accept either:
    - http://host:8000
    - http://host:8000/api/v1

    Returns: (root_base_url, api_v1_base_url)
    """
    base = str(raw_base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url is required")
    if base.endswith("/api/v1"):
        root = base[: -len("/api/v1")].rstrip("/")
    else:
        root = base
    api_v1 = f"{root}/api/v1"
    return root, api_v1


def _join(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _parse_json(resp: httpx.Response) -> Any:
    try:
        return resp.json() if resp.content else None
    except Exception:
        return None


def _build_headers(*, tenant_id: str, user_id: str | None, token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif user_id:
        headers["X-User-ID"] = user_id
    return headers


def _check_ready(client: httpx.Client, *, api_base: str) -> tuple[bool, dict[str, Any]]:
    url = _join(api_base, "health/ready")
    try:
        resp = client.get(url)
    except Exception as exc:  # noqa: BLE001
        return False, {"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    payload = _parse_json(resp)
    ok = resp.status_code == 200 and isinstance(payload, dict) and payload.get("ok") is True
    return bool(ok), {"url": url, "status_code": resp.status_code, "body": payload}


def _build_smoke_test_command(
    *,
    out_path: Path,
    base_url: str,
    tenant_id: str,
    auth_mode: str | None,
    user_id: str | None,
    token: str | None,
    allow_unstructured: bool,
    verbose: bool,
) -> list[str]:
    cmd: list[str] = [
        sys.executable,
        "scripts/smoke_test.py",
        "--base-url",
        base_url,
        "--tenant-id",
        tenant_id,
        "--out",
        str(out_path),
    ]
    for flag, value in (("--auth-mode", auth_mode), ("--token", token), ("--user-id", user_id)):
        if value:
            cmd.extend([flag, value])
    if allow_unstructured:
        cmd.append("--allow-unstructured")
    if verbose:
        cmd.append("--verbose")
    return cmd


def _redact_command_args(cmd: list[str]) -> list[str]:
    cmd_redacted: list[str] = []
    redact_next = False
    for arg in cmd:
        if redact_next:
            cmd_redacted.append("***")
            redact_next = False
            continue
        if arg in {"--token", "--password"}:
            cmd_redacted.append(arg)
            redact_next = True
            continue
        cmd_redacted.append(arg)
    return cmd_redacted


def _load_json_file_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _run_smoke_test(
    *,
    repo_root: Path,
    base_url: str,
    tenant_id: str,
    auth_mode: str | None,
    user_id: str | None,
    token: str | None,
    allow_unstructured: bool,
    verbose: bool,
) -> tuple[int, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="mimirq-dr-") as tmp:
        out_path = Path(tmp) / "smoke_report.json"
        cmd = _build_smoke_test_command(
            out_path=out_path,
            base_url=base_url,
            tenant_id=tenant_id,
            auth_mode=auth_mode,
            user_id=user_id,
            token=token,
            allow_unstructured=allow_unstructured,
            verbose=verbose,
        )

        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, check=False)
        report: dict[str, Any] = {
            "command": _redact_command_args(cmd),
            "exit_code": int(proc.returncode),
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
        report["report"] = _load_json_file_if_exists(out_path)

        return int(proc.returncode), report


def _get_index_audit(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
    dataset_id: str,
    max_check_ids: int,
    milvus_list_limit: int,
    sample_limit: int,
) -> tuple[bool, dict[str, Any]]:
    url = _join(
        api_base,
        (
            "observability/index-audit"
            f"?dataset_id={dataset_id}"
            f"&max_check_ids={int(max_check_ids)}"
            f"&milvus_list_limit={int(milvus_list_limit)}"
            f"&sample_limit={int(sample_limit)}"
        ),
    )
    try:
        resp = client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return False, {"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    body = _parse_json(resp)
    ok_http = resp.status_code == 200 and isinstance(body, dict)
    return bool(ok_http), {"url": url, "status_code": resp.status_code, "body": body}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DR restore verification: ready + smoke + index-audit (PII-safe).")
    parser.add_argument("--base-url", default=os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000"))
    parser.add_argument(
        "--tenant-id",
        default=os.getenv("NEXT_PUBLIC_TENANT_ID", "00000000-0000-0000-0000-000000000000"),
    )
    parser.add_argument("--auth-mode", default=None, help="Override auth mode (jwt|header).")
    parser.add_argument("--user-id", default=os.getenv("NEXT_PUBLIC_USER_ID", ""), help="X-User-ID (AUTH_MODE=header).")
    parser.add_argument("--token", default=os.getenv("MIMIRQ_DR_ADMIN_TOKEN", ""), help="Bearer token (AUTH_MODE=jwt).")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip smoke test step.")
    parser.add_argument("--skip-index-audit", action="store_true", help="Skip index-audit step.")
    parser.add_argument(
        "--dataset-id",
        default="",
        help="Explicit dataset id for index-audit (otherwise uses smoke dataset).",
    )
    parser.add_argument("--max-check-ids", type=int, default=2000)
    parser.add_argument("--milvus-list-limit", type=int, default=500)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument(
        "--allow-unstructured",
        action="store_true",
        help="Allow smoke test to pass without structured output.",
    )
    parser.add_argument("--out", default="", help="Write JSON report to file path (best-effort).")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _build_report(*, api_base: str, tenant_id: str) -> dict[str, Any]:
    return {
        "schema": "mimirq.dr_verify_restore.v1",
        "ran_at": _utc_now_iso(),
        "api_base": api_base,
        "tenant_id": tenant_id,
        "steps": {},
        "ok": False,
    }


def _write_report(path_text: str, report: dict[str, Any]) -> None:
    if path_text:
        Path(path_text).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_smoke_dataset_id(args: argparse.Namespace, smoke_report: dict[str, Any] | None) -> str:
    dataset_id = str(args.dataset_id or "").strip()
    if dataset_id or not isinstance(smoke_report, dict):
        return dataset_id
    smoke_payload = smoke_report.get("report")
    if not isinstance(smoke_payload, dict):
        return ""
    return str(smoke_payload.get("dataset_id") or "").strip()


def _run_index_audit_step(
    *,
    args: argparse.Namespace,
    timeout: httpx.Timeout,
    limits: httpx.Limits,
    api_base: str,
    tenant_id: str,
    user_id: str | None,
    token: str | None,
    smoke_report: dict[str, Any] | None,
    report: dict[str, Any],
) -> bool:
    dataset_id = _resolve_smoke_dataset_id(args, smoke_report)
    if not dataset_id:
        report["steps"]["index_audit"] = {
            "ok": False,
            "error": "no_dataset_id (pass --dataset-id or run smoke step)",
        }
        return False

    headers = _build_headers(tenant_id=tenant_id, user_id=user_id, token=token)
    with httpx.Client(timeout=timeout, limits=limits, follow_redirects=False, trust_env=False) as client:
        ok_http, audit = _get_index_audit(
            client,
            api_base=api_base,
            headers=headers,
            dataset_id=dataset_id,
            max_check_ids=int(args.max_check_ids),
            milvus_list_limit=int(args.milvus_list_limit),
            sample_limit=int(args.sample_limit),
        )
    report["steps"]["index_audit"] = audit
    if not ok_http:
        return False

    body = (audit or {}).get("body") if isinstance(audit, dict) else None
    if not isinstance(body, dict):
        return False
    vector_id_missing = int(body.get("vector_id_missing") or 0)
    missing_in_backend = int(body.get("vector_ids_missing_in_backend") or 0)
    orphan_sample = body.get("milvus_orphan_ids_sample")
    orphan_count = len(orphan_sample) if isinstance(orphan_sample, list) else 0
    report["steps"]["index_audit_check"] = {
        "vector_id_missing": vector_id_missing,
        "vector_ids_missing_in_backend": missing_in_backend,
        "milvus_orphan_ids_sample_count": orphan_count,
    }
    return (vector_id_missing == 0) and (missing_in_backend == 0) and (orphan_count == 0)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    started = time.perf_counter()
    _root_base, api_base = _normalize_base_urls(str(args.base_url or ""))
    tenant_id = str(args.tenant_id or "").strip()
    user_id = str(args.user_id or "").strip() or None
    token = str(args.token or "").strip() or None
    report = _build_report(api_base=api_base, tenant_id=tenant_id)

    # Readiness check (no auth required).
    timeout = httpx.Timeout(10.0)
    limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
    with httpx.Client(timeout=timeout, limits=limits, follow_redirects=False, trust_env=False) as client:
        ready_ok, ready = _check_ready(client, api_base=api_base)
        report["steps"]["ready"] = ready
        if not ready_ok:
            report["error"] = "readiness_failed"
            _write_report(str(args.out or ""), report)
            print(json.dumps(report, ensure_ascii=False))
            return 2

    # Auth is required for index-audit. We allow smoke-only verification without auth.
    if (not args.skip_index_audit) and (not token) and (not user_id):
        report["warning"] = "no_admin_credentials; index-audit will be skipped"
        args.skip_index_audit = True

    repo_root = Path(__file__).resolve().parents[1]

    # Smoke test (client-side end-to-end verification).
    smoke_ok = True
    smoke_report: dict[str, Any] | None = None
    if not bool(args.skip_smoke):
        exit_code, smoke_report = _run_smoke_test(
            repo_root=repo_root,
            base_url=str(args.base_url),
            tenant_id=tenant_id,
            auth_mode=(str(args.auth_mode).strip() if args.auth_mode else None),
            user_id=user_id,
            token=token,
            allow_unstructured=bool(args.allow_unstructured),
            verbose=bool(args.verbose),
        )
        smoke_ok = exit_code == 0
        report["steps"]["smoke_test"] = smoke_report

    # Index audit (admin-only endpoint).
    audit_ok = True
    if not bool(args.skip_index_audit):
        audit_ok = _run_index_audit_step(
            args=args,
            timeout=timeout,
            limits=limits,
            api_base=api_base,
            tenant_id=tenant_id,
            user_id=user_id,
            token=token,
            smoke_report=smoke_report,
            report=report,
        )

    report["ok"] = bool(ready_ok and smoke_ok and audit_ok)
    report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    _write_report(str(args.out or ""), report)

    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
