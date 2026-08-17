#!/usr/bin/env python3
"""Remote admin/permission smoke matrix.

Uses only the Python standard library so it can run on production-like hosts.
"""

import argparse
import json
import mimetypes
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
SETTINGS_STATUS_PATH = "/api/v1/settings/status"
GROUPS_PATH = "/api/v1/groups/"
ACCESS_GRAPH_SUMMARY_PATH = "/api/v1/audit/access-graph/summary"
ACCESS_GRAPH_EXPORT_PATH = "/api/v1/audit/access-graph/export?export_format=json&limit=10"
DATASETS_PATH = "/api/v1/datasets/"
DOCUMENT_UPLOAD_PATH = "/api/v1/documents/upload"

ApiResponse = tuple[int, Any, float]
StepList = list[dict[str, Any]]


class LiveApi:
    def __init__(
        self,
        base_url: str,
        tenant_id: str,
        account_id: str,
        user_id: str,
        timeout: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.headers = {
            "X-Tenant-ID": tenant_id,
            "X-Account-ID": account_id,
            "X-User-ID": user_id,
        }

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> ApiResponse:
        headers = dict(self.headers)
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request(
            method,
            path,
            data=data,
            headers=headers,
            timeout=int(timeout or self.timeout),
        )

    def multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        timeout: int | None = None,
    ) -> ApiResponse:
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
        return self._request(
            method,
            path,
            data=b"".join(chunks),
            headers=headers,
            timeout=int(timeout or self.timeout),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None,
        headers: dict[str, str],
        timeout: int,
    ) -> ApiResponse:
        req = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a small remote admin/permission verification matrix.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--admin-account-id", default="demo")
    parser.add_argument("--admin-user-id", default="demo")
    parser.add_argument("--outsider-account-id", default="outsider")
    parser.add_argument("--outsider-user-id", default="outsider")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--postgres-container", default="docker-mimirq-postgres-1")
    return parser


def snippet(body: Any, limit: int = 1200) -> str:
    if isinstance(body, str):
        return body[:limit]
    return json.dumps(body, ensure_ascii=False, default=str)[:limit]


def status_matches_expected(status: int, expected_statuses: list[int]) -> bool:
    return int(status) in {int(item) for item in (expected_statuses or [])}


def build_case_result(
    name: str,
    *,
    status: int,
    body: Any,
    elapsed: float,
    expected_statuses: list[int],
) -> dict[str, Any]:
    item = {
        "name": name,
        "status_code": int(status),
        "elapsed_sec": round(float(elapsed), 3),
        "expected_statuses": [int(value) for value in expected_statuses],
        "ok": status_matches_expected(status, expected_statuses),
    }
    if not item["ok"]:
        item["response"] = snippet(body)
    return item


def append_case_result(
    steps: StepList,
    name: str,
    response: ApiResponse,
    expected_statuses: list[int],
) -> tuple[int, Any]:
    status, body, elapsed = response
    steps.append(
        build_case_result(
            name,
            status=status,
            body=body,
            elapsed=elapsed,
            expected_statuses=expected_statuses,
        )
    )
    return status, body


def expect_case_result(
    steps: StepList,
    name: str,
    response: ApiResponse,
    expected_statuses: list[int],
    error_message: str,
) -> Any:
    status, body = append_case_result(steps, name, response, expected_statuses)
    if not status_matches_expected(status, expected_statuses):
        raise RuntimeError(f"{error_message}: {snippet(body)}")
    return body


def expect_json_case(
    api: LiveApi,
    *,
    method: str,
    path: str,
    steps: StepList,
    name: str,
    expected_statuses: list[int],
    error_message: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    return expect_case_result(
        steps,
        name,
        api.json(method, path, payload=payload),
        expected_statuses,
        error_message,
    )


def record_json_case(
    api: LiveApi,
    *,
    method: str,
    path: str,
    steps: StepList,
    name: str,
    expected_statuses: list[int],
    payload: dict[str, Any] | None = None,
) -> None:
    append_case_result(
        steps,
        name,
        api.json(method, path, payload=payload),
        expected_statuses,
    )


def expect_multipart_case(
    api: LiveApi,
    *,
    method: str,
    path: str,
    fields: dict[str, str],
    file_path: Path,
    steps: StepList,
    name: str,
    expected_statuses: list[int],
    error_message: str,
) -> Any:
    return expect_case_result(
        steps,
        name,
        api.multipart(method, path, fields=fields, file_path=file_path),
        expected_statuses,
        error_message,
    )


def write_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Permission Smoke\n\n"
        "This document validates ACL and admin-only behavior.\n\n"
        "Only the allowlisted principal should keep read access after the ACL "
        "update.\n",
        encoding="utf-8",
    )


def force_member_role_via_docker(
    *,
    tenant_id: str,
    account_id: str,
    role: str,
    postgres_container: str = "docker-mimirq-postgres-1",
    timeout: int = 30,
) -> tuple[bool, str]:
    tenant_sql = str(tenant_id or "").replace("'", "''")
    account_sql = str(account_id or "").replace("'", "''")
    role_sql = str(role or "").replace("'", "''")
    sql = (
        "UPDATE tenant_members "
        f"SET role='{role_sql}', is_active=true "
        f"WHERE tenant_id='{tenant_sql}' AND user_id='{account_sql}';"
    )
    result = subprocess.run(  # noqa: S603
        [
            "docker",
            "exec",
            "-i",
            postgres_container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "mimirq",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        timeout=int(timeout),
        check=False,
    )
    output = (str(result.stdout or "") + str(result.stderr or "")).strip()
    return bool(result.returncode == 0), output[:1200]


def build_artifact_dir(artifact_dir: str, run_id: str) -> Path:
    target = artifact_dir or f"artifacts/permission-matrix/{run_id}"
    return Path(target).resolve()


def normalize_outsider_settings(
    args: argparse.Namespace,
    outsider_api: LiveApi,
    steps: StepList,
) -> None:
    response = outsider_api.json("GET", SETTINGS_STATUS_PATH)
    status = response[0]
    should_force_role = (
        not status_matches_expected(status, [401, 403])
        and int(status) == 200
        and str(args.outsider_account_id) != str(args.admin_account_id)
    )
    if should_force_role:
        forced_ok, forced_output = force_member_role_via_docker(
            tenant_id=str(args.tenant_id),
            account_id=str(args.outsider_account_id),
            role="viewer",
            postgres_container=str(args.postgres_container),
            timeout=min(int(args.timeout), 60),
        )
        steps.append(
            {
                "name": "force_outsider_role",
                "ok": bool(forced_ok),
                "status_code": 0 if forced_ok else 1,
                "elapsed_sec": 0.0,
                "detail": forced_output,
            }
        )
        if forced_ok:
            response = outsider_api.json("GET", SETTINGS_STATUS_PATH)
    expect_case_result(
        steps,
        "settings_status_outsider",
        response,
        [401, 403],
        "outsider settings/status unexpectedly allowed",
    )


def run_remote_boundary_checks(
    admin_api: LiveApi,
    outsider_api: LiveApi,
    steps: StepList,
) -> None:
    cases = [
        (
            "groups_admin",
            admin_api,
            GROUPS_PATH,
            [200],
            "admin groups failed",
        ),
        (
            "groups_outsider",
            outsider_api,
            GROUPS_PATH,
            [401, 403],
            "outsider groups unexpectedly allowed",
        ),
        (
            "access_graph_summary_admin",
            admin_api,
            ACCESS_GRAPH_SUMMARY_PATH,
            [200],
            "admin access-graph summary failed",
        ),
        (
            "access_graph_summary_outsider",
            outsider_api,
            ACCESS_GRAPH_SUMMARY_PATH,
            [401, 403],
            "outsider access-graph summary unexpectedly allowed",
        ),
        (
            "access_graph_export_admin",
            admin_api,
            ACCESS_GRAPH_EXPORT_PATH,
            [200],
            "admin access-graph export failed",
        ),
        (
            "access_graph_export_outsider",
            outsider_api,
            ACCESS_GRAPH_EXPORT_PATH,
            [401, 403],
            "outsider access-graph export unexpectedly allowed",
        ),
    ]
    for name, api, path, expected_statuses, error_message in cases:
        expect_json_case(
            api,
            method="GET",
            path=path,
            steps=steps,
            name=name,
            expected_statuses=expected_statuses,
            error_message=error_message,
        )


def create_dataset(
    admin_api: LiveApi,
    *,
    run_id: str,
    steps: StepList,
) -> str:
    body = expect_json_case(
        admin_api,
        method="POST",
        path=DATASETS_PATH,
        steps=steps,
        name="create_dataset",
        expected_statuses=[200, 201],
        error_message="create dataset failed",
        payload={
            "name": f"Permission Matrix {run_id}",
            "description": "Admin/permission verification dataset",
            "permission": "all_team_members",
            "default_parser_backend": "basic",
            "default_chunk_strategy": "langchain_recursive",
        },
    )
    return str((body or {}).get("id") or (body or {}).get("dataset_id") or "")


def upload_document(
    admin_api: LiveApi,
    *,
    dataset_id: str,
    fixture: Path,
    steps: StepList,
) -> str:
    body = expect_multipart_case(
        admin_api,
        method="POST",
        path=DOCUMENT_UPLOAD_PATH,
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
        steps=steps,
        name="upload_document",
        expected_statuses=[200, 201],
        error_message="upload failed",
    )
    return str((body or {}).get("id") or (body or {}).get("document_id") or "")


def poll_document(
    admin_api: LiveApi,
    *,
    document_id: str,
    timeout: int,
    steps: StepList,
) -> None:
    deadline = time.time() + max(60, int(timeout))
    while time.time() < deadline:
        body = expect_json_case(
            admin_api,
            method="GET",
            path=f"/api/v1/documents/{document_id}",
            steps=steps,
            name="poll_document",
            expected_statuses=[200],
            error_message="document poll failed",
        )
        if str((body or {}).get("status") or "").lower() == "completed":
            break
        time.sleep(2)


def update_document_access(
    args: argparse.Namespace,
    admin_api: LiveApi,
    outsider_api: LiveApi,
    *,
    document_id: str,
    steps: StepList,
    summary: dict[str, Any],
) -> None:
    document_access_path = f"/api/v1/documents/{document_id}/access"
    expect_json_case(
        admin_api,
        method="PUT",
        path=document_access_path,
        steps=steps,
        name="document_access_put_admin",
        expected_statuses=[200],
        error_message="admin document access put failed",
        payload={
            "mode": "partial_members",
            "partial_member_list": [args.admin_account_id],
            "partial_group_list": [],
        },
    )
    summary["document_access_admin"] = expect_json_case(
        admin_api,
        method="GET",
        path=document_access_path,
        steps=steps,
        name="document_access_get_admin",
        expected_statuses=[200],
        error_message="admin document access get failed",
    )
    expect_json_case(
        outsider_api,
        method="GET",
        path=document_access_path,
        steps=steps,
        name="document_access_get_outsider",
        expected_statuses=[401, 403],
        error_message="outsider document access unexpectedly allowed",
    )
    expect_json_case(
        outsider_api,
        method="PUT",
        path=document_access_path,
        steps=steps,
        name="document_access_put_outsider",
        expected_statuses=[401, 403],
        error_message="outsider document access update unexpectedly allowed",
        payload={
            "mode": "inherit",
            "partial_member_list": [],
            "partial_group_list": [],
        },
    )


def cleanup_dataset(admin_api: LiveApi, *, dataset_id: str, steps: StepList) -> None:
    if not dataset_id:
        return
    record_json_case(
        admin_api,
        method="POST",
        path=f"/api/v1/datasets/{dataset_id}/purge?dry_run=false&max_delete=1000",
        steps=steps,
        name="cleanup_purge_dataset",
        expected_statuses=[200],
        payload={},
    )
    record_json_case(
        admin_api,
        method="DELETE",
        path=f"/api/v1/datasets/{dataset_id}",
        steps=steps,
        name="cleanup_delete_dataset",
        expected_statuses=[200, 204],
    )


def run_matrix(
    args: argparse.Namespace,
    admin_api: LiveApi,
    outsider_api: LiveApi,
    *,
    run_id: str,
    fixture: Path,
    steps: StepList,
    resource_ids: dict[str, str],
    summary: dict[str, Any],
) -> tuple[str, str]:
    expect_json_case(
        admin_api,
        method="GET",
        path=SETTINGS_STATUS_PATH,
        steps=steps,
        name="settings_status_admin",
        expected_statuses=[200],
        error_message="admin settings/status failed",
    )
    normalize_outsider_settings(args, outsider_api, steps)
    run_remote_boundary_checks(admin_api, outsider_api, steps)
    dataset_id = create_dataset(admin_api, run_id=run_id, steps=steps)
    resource_ids["dataset_id"] = dataset_id
    document_id = upload_document(
        admin_api,
        dataset_id=dataset_id,
        fixture=fixture,
        steps=steps,
    )
    resource_ids["document_id"] = document_id
    poll_document(
        admin_api,
        document_id=document_id,
        timeout=int(args.timeout),
        steps=steps,
    )
    update_document_access(
        args,
        admin_api,
        outsider_api,
        document_id=document_id,
        steps=steps,
        summary=summary,
    )
    cleanup_dataset(admin_api, dataset_id=dataset_id, steps=steps)
    return dataset_id, document_id


def build_output(
    summary: dict[str, Any],
    dataset_id: str,
    document_id: str,
) -> dict[str, Any]:
    return {
        "ok": summary.get("ok"),
        "artifact_dir": summary.get("artifact_dir"),
        "dataset_id": dataset_id or None,
        "document_id": document_id or None,
        "error": summary.get("error"),
    }


def main() -> int:
    args = build_parser().parse_args()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    artifact_dir = build_artifact_dir(args.artifact_dir, run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixture = artifact_dir / "permission-fixture.md"
    write_fixture(fixture)

    admin_api = LiveApi(
        args.base_url,
        args.tenant_id,
        args.admin_account_id,
        args.admin_user_id,
        args.timeout,
    )
    outsider_api = LiveApi(
        args.base_url,
        args.tenant_id,
        args.outsider_account_id,
        args.outsider_user_id,
        args.timeout,
    )

    steps: StepList = []
    summary: dict[str, Any] = {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
    }
    resource_ids = {"dataset_id": "", "document_id": ""}
    try:
        dataset_id, document_id = run_matrix(
            args,
            admin_api,
            outsider_api,
            run_id=run_id,
            fixture=fixture,
            steps=steps,
            resource_ids=resource_ids,
            summary=summary,
        )
        summary["ok"] = all(bool(step.get("ok")) for step in steps)
        summary["dataset_id"] = dataset_id
        summary["document_id"] = document_id
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["error"] = str(exc)
    finally:
        summary["steps"] = steps
        report_path = artifact_dir / "report.json"
        report_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                build_output(
                    summary,
                    resource_ids["dataset_id"],
                    resource_ids["document_id"],
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
