#!/usr/bin/env python3
"""Remote admin/permission smoke matrix.

Uses only the Python standard library so it can run on production-like hosts.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


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
        boundary = f"----MimirQPerms{uuid.uuid4().hex}"
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
        req = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urlopen(req, timeout=timeout) as resp:
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


def snippet(body: Any, limit: int = 1200) -> str:
    if isinstance(body, str):
        return body[:limit]
    return json.dumps(body, ensure_ascii=False, default=str)[:limit]


def status_matches_expected(status: int, expected_statuses: list[int]) -> bool:
    return int(status) in {int(item) for item in (expected_statuses or [])}


def build_case_result(name: str, *, status: int, body: Any, elapsed: float, expected_statuses: list[int]) -> dict[str, Any]:
    item = {
        "name": name,
        "status_code": int(status),
        "elapsed_sec": round(float(elapsed), 3),
        "expected_statuses": [int(v) for v in expected_statuses],
        "ok": status_matches_expected(status, expected_statuses),
    }
    if not item["ok"]:
        item["response"] = snippet(body)
    return item


def write_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Permission Smoke\n\n"
        "This document validates ACL and admin-only behavior.\n\n"
        "Only the allowlisted principal should keep read access after the ACL update.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small remote admin/permission verification matrix.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--admin-account-id", default="demo")
    parser.add_argument("--admin-user-id", default="demo")
    parser.add_argument("--outsider-account-id", default="outsider")
    parser.add_argument("--outsider-user-id", default="outsider")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir or f"artifacts/permission-matrix/{run_id}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixture = artifact_dir / "permission-fixture.md"
    write_fixture(fixture)

    admin_api = LiveApi(args.base_url, args.tenant_id, args.admin_account_id, args.admin_user_id, args.timeout)
    outsider_api = LiveApi(args.base_url, args.tenant_id, args.outsider_account_id, args.outsider_user_id, args.timeout)

    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"ok": False, "artifact_dir": str(artifact_dir), "base_url": args.base_url}

    dataset_id = ""
    document_id = ""
    try:
        status, body, elapsed = admin_api.json("GET", "/api/v1/settings/status")
        steps.append(build_case_result("settings_status_admin", status=status, body=body, elapsed=elapsed, expected_statuses=[200]))
        if not status_matches_expected(status, [200]):
            raise RuntimeError(f"admin settings/status failed: {snippet(body)}")

        status, body, elapsed = outsider_api.json("GET", "/api/v1/settings/status")
        steps.append(build_case_result("settings_status_outsider", status=status, body=body, elapsed=elapsed, expected_statuses=[401, 403]))
        if not status_matches_expected(status, [401, 403]):
            raise RuntimeError(f"outsider settings/status unexpectedly allowed: {snippet(body)}")

        status, body, elapsed = admin_api.json("GET", "/api/v1/groups/")
        steps.append(build_case_result("groups_admin", status=status, body=body, elapsed=elapsed, expected_statuses=[200]))
        if not status_matches_expected(status, [200]):
            raise RuntimeError(f"admin groups failed: {snippet(body)}")

        status, body, elapsed = outsider_api.json("GET", "/api/v1/groups/")
        steps.append(build_case_result("groups_outsider", status=status, body=body, elapsed=elapsed, expected_statuses=[401, 403]))
        if not status_matches_expected(status, [401, 403]):
            raise RuntimeError(f"outsider groups unexpectedly allowed: {snippet(body)}")

        status, body, elapsed = admin_api.json(
            "POST",
            "/api/v1/datasets/",
            payload={
                "name": f"Permission Matrix {run_id}",
                "description": "Admin/permission verification dataset",
                "permission": "all_team_members",
                "default_parser_backend": "basic",
                "default_chunk_strategy": "langchain_recursive",
            },
        )
        steps.append(build_case_result("create_dataset", status=status, body=body, elapsed=elapsed, expected_statuses=[200, 201]))
        if not status_matches_expected(status, [200, 201]):
            raise RuntimeError(f"create dataset failed: {snippet(body)}")
        dataset_id = str((body or {}).get("id") or (body or {}).get("dataset_id") or "")

        status, body, elapsed = admin_api.multipart(
            "POST",
            "/api/v1/documents/upload",
            fields={
                "dataset_id": dataset_id,
                "parser_backend": "basic",
                "chunk_strategy": "langchain_recursive",
                "governance_enabled": "true",
                "chunk_vector_enabled": "true",
                "bm25_index_enabled": "true",
                "kg_enabled": "false",
                "event_vector_enabled": "false",
                "entity_vector_enabled": "false",
            },
            file_path=fixture,
        )
        steps.append(build_case_result("upload_document", status=status, body=body, elapsed=elapsed, expected_statuses=[200, 201]))
        if not status_matches_expected(status, [200, 201]):
            raise RuntimeError(f"upload failed: {snippet(body)}")
        document_id = str((body or {}).get("id") or (body or {}).get("document_id") or "")

        deadline = time.time() + max(60, int(args.timeout))
        while time.time() < deadline:
            status, body, elapsed = admin_api.json("GET", f"/api/v1/documents/{document_id}")
            steps.append(build_case_result("poll_document", status=status, body=body, elapsed=elapsed, expected_statuses=[200]))
            if not status_matches_expected(status, [200]):
                raise RuntimeError(f"document poll failed: {snippet(body)}")
            if str((body or {}).get("status") or "").lower() == "completed":
                break
            time.sleep(2)

        status, body, elapsed = admin_api.json("PUT", f"/api/v1/documents/{document_id}/access", payload={"mode": "partial_members", "partial_member_list": [args.admin_account_id], "partial_group_list": []})
        steps.append(build_case_result("document_access_put_admin", status=status, body=body, elapsed=elapsed, expected_statuses=[200]))
        if not status_matches_expected(status, [200]):
            raise RuntimeError(f"admin document access put failed: {snippet(body)}")

        status, body, elapsed = admin_api.json("GET", f"/api/v1/documents/{document_id}/access")
        steps.append(build_case_result("document_access_get_admin", status=status, body=body, elapsed=elapsed, expected_statuses=[200]))
        if not status_matches_expected(status, [200]):
            raise RuntimeError(f"admin document access get failed: {snippet(body)}")
        summary["document_access_admin"] = body

        status, body, elapsed = outsider_api.json("GET", f"/api/v1/documents/{document_id}/access")
        steps.append(build_case_result("document_access_get_outsider", status=status, body=body, elapsed=elapsed, expected_statuses=[401, 403]))
        if not status_matches_expected(status, [401, 403]):
            raise RuntimeError(f"outsider document access unexpectedly allowed: {snippet(body)}")

        status, body, elapsed = outsider_api.json("PUT", f"/api/v1/documents/{document_id}/access", payload={"mode": "inherit", "partial_member_list": [], "partial_group_list": []})
        steps.append(build_case_result("document_access_put_outsider", status=status, body=body, elapsed=elapsed, expected_statuses=[401, 403]))
        if not status_matches_expected(status, [401, 403]):
            raise RuntimeError(f"outsider document access update unexpectedly allowed: {snippet(body)}")

        if dataset_id:
            status, body, elapsed = admin_api.json("POST", f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000", payload={})
            steps.append(build_case_result("cleanup_purge_dataset", status=status, body=body, elapsed=elapsed, expected_statuses=[200]))
            status, body, elapsed = admin_api.json("DELETE", f"/api/v1/datasets/{dataset_id}")
            steps.append(build_case_result("cleanup_delete_dataset", status=status, body=body, elapsed=elapsed, expected_statuses=[200, 204]))

        summary["ok"] = all(bool(step.get("ok")) for step in steps)
        summary["dataset_id"] = dataset_id
        summary["document_id"] = document_id
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
        summary["steps"] = steps
        (artifact_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": summary.get("ok"), "artifact_dir": summary.get("artifact_dir"), "dataset_id": dataset_id or None, "document_id": document_id or None, "error": summary.get("error")}, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
