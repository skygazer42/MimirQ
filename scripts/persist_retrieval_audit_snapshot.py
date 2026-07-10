#!/usr/bin/env python3
"""Persist a sanitized retrieval_audit snapshot into dataset metadata."""


import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.report_service import sanitize_retrieval_audit_snapshot  # noqa: E402

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
RequestJsonFn = Callable[..., dict[str, Any]]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _write_json(path: str | os.PathLike[str], payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json_dumps(payload) + "\n", encoding="utf-8")


def _load_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary JSON must be an object")
    return payload


def _api_url(base_url: str, path: str) -> str:
    base = _text(base_url).rstrip("/")
    if not base:
        raise ValueError("base_url is required")
    if not base.endswith("/api/v1"):
        base = f"{base}/api/v1"
    return f"{base}/{path.lstrip('/')}"


def _headers(
    *,
    tenant_id: str,
    account_id: str,
    user_id: str,
    bearer: str,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if _text(tenant_id):
        headers["X-Tenant-ID"] = _text(tenant_id)
    if _text(account_id):
        headers["X-Account-ID"] = _text(account_id)
    if _text(user_id):
        headers["X-User-ID"] = _text(user_id)
    if _text(bearer):
        headers["Authorization"] = f"Bearer {_text(bearer)}"
    return headers


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text) if text.strip() else {}


def _snippet(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")[:800]


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            body = _decode_json(response.read())
            if isinstance(body, dict):
                return body
            raise RuntimeError("response JSON must be an object")
    except HTTPError as exc:
        body = exc.read()
        raise RuntimeError(f"HTTP {exc.code}: {_snippet(body)}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


def load_retrieval_audit_payload(summary_path: str | os.PathLike[str]) -> dict[str, Any]:
    summary = _load_json(summary_path)
    raw = summary.get("retrieval_audit")
    if not isinstance(raw, dict):
        raise ValueError("summary JSON must contain retrieval_audit object")
    audit = sanitize_retrieval_audit_snapshot(raw)
    return audit.model_dump(mode="json")


def _safe_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _gate_names(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if name:
            names.add(name)
    return names


def _require_subset(*, field: str, expected: set[str], actual: set[str]) -> None:
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"report retrieval_audit missing {field}: {', '.join(missing)}")


def _verify_failure_categories(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    missing: list[str] = []
    for key, raw_value in expected.items():
        try:
            expected_count = int(raw_value or 0)
            actual_count = int(actual.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if expected_count > 0 and actual_count < expected_count:
            missing.append(str(key))
    if missing:
        raise RuntimeError(f"report retrieval_audit missing failure_categories: {', '.join(sorted(missing))}")


def verify_report_consumed_retrieval_audit(
    *,
    expected: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    audit = report.get("retrieval_audit")
    if not isinstance(audit, dict):
        raise RuntimeError("report retrieval_audit is missing")

    if _text(expected.get("status")).lower() == "failed" and _text(audit.get("status")).lower() != "failed":
        raise RuntimeError("report retrieval_audit status did not preserve failed state")

    _require_subset(
        field="plugin_refs",
        expected=set(_safe_list(expected.get("plugin_refs"))),
        actual=set(_safe_list(audit.get("plugin_refs"))),
    )
    _require_subset(
        field="plugin_package_hashes",
        expected=set(_safe_list(expected.get("plugin_package_hashes"))),
        actual=set(_safe_list(audit.get("plugin_package_hashes"))),
    )
    _require_subset(
        field="gates",
        expected=_gate_names(expected.get("gates")),
        actual=_gate_names(audit.get("gates")),
    )
    expected_categories = expected.get("failure_categories") if isinstance(expected.get("failure_categories"), dict) else {}
    actual_categories = audit.get("failure_categories") if isinstance(audit.get("failure_categories"), dict) else {}
    _verify_failure_categories(expected_categories, actual_categories)
    return audit


def persist_retrieval_audit_snapshot(
    *,
    summary_path: str | os.PathLike[str],
    base_url: str,
    dataset_id: str,
    tenant_id: str,
    account_id: str,
    user_id: str,
    bearer: str,
    timeout: float,
    verify_report: bool = False,
    request_json: RequestJsonFn = _request_json,
) -> dict[str, Any]:
    dataset_id = _text(dataset_id)
    if not dataset_id:
        raise ValueError("dataset_id is required")
    payload = load_retrieval_audit_payload(summary_path)
    url = _api_url(base_url, f"datasets/{dataset_id}/retrieval-audit")
    headers = _headers(tenant_id=tenant_id, account_id=account_id, user_id=user_id, bearer=bearer)
    persisted = request_json(
        method="PUT",
        url=url,
        headers=headers,
        payload=payload,
        timeout=float(timeout),
    )
    if not verify_report:
        return persisted

    report = request_json(
        method="GET",
        url=_api_url(base_url, f"reports/datasets/{dataset_id}"),
        headers=headers,
        payload=None,
        timeout=float(timeout),
    )
    report_audit = verify_report_consumed_retrieval_audit(expected=payload, report=report)
    return {
        "persisted": persisted,
        "report_verified": True,
        "report_retrieval_audit": report_audit,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, help="Readiness summary JSON containing retrieval_audit.")
    parser.add_argument(
        "--base-url",
        default=(
            os.getenv("MIMIRQ_BASE_URL")
            or os.getenv("MIMIRQ_API_BASE_URL")
            or os.getenv("BACKEND_BASE_URL")
            or os.getenv("CHANGZHOU_DIFY_MIMIRQ_BASE_URL")
            or "http://127.0.0.1:8000"
        ),
        help="MimirQ backend base URL; root or /api/v1 is accepted.",
    )
    parser.add_argument("--dataset-id", required=True, help="Target dataset UUID.")
    parser.add_argument("--tenant-id", default=os.getenv("MIMIRQ_TENANT_ID") or DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default=os.getenv("MIMIRQ_ACCOUNT_ID") or "demo")
    parser.add_argument("--user-id", default=os.getenv("MIMIRQ_USER_ID") or "demo")
    parser.add_argument("--bearer", default=os.getenv("MIMIRQ_API_TOKEN") or os.getenv("AUTH_TOKEN") or "")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("MIMIRQ_API_TIMEOUT") or "60"))
    parser.add_argument("--verify-report", action="store_true", help="GET the dataset report after writeback and verify it consumed the audit.")
    parser.add_argument("--out", default="", help="Optional path to write the sanitized API response JSON.")
    args = parser.parse_args(argv)

    response = persist_retrieval_audit_snapshot(
        summary_path=args.summary,
        base_url=args.base_url,
        dataset_id=args.dataset_id,
        tenant_id=args.tenant_id,
        account_id=args.account_id,
        user_id=args.user_id,
        bearer=args.bearer,
        timeout=float(args.timeout),
        verify_report=bool(args.verify_report),
    )
    if args.out:
        _write_json(args.out, response)
    print(_json_dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
