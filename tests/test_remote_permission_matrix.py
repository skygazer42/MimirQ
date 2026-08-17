import json
import sys
from pathlib import Path

import pytest

import scripts.remote_permission_matrix as mod


@pytest.fixture
def fixed_run_id(monkeypatch: pytest.MonkeyPatch) -> str:
    run_id = "20260816-010203"
    monkeypatch.setattr(mod.time, "strftime", lambda _fmt: run_id)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    return run_id


class FakeLiveApi:
    def __init__(
        self,
        actor: str,
        calls: list[dict[str, object]],
        settings_statuses: list[int] | None = None,
        upload_status: int = 201,
    ) -> None:
        self.actor = actor
        self.calls = calls
        self.settings_statuses = list(settings_statuses or [])
        self.upload_status = upload_status

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        timeout: int | None = None,
    ) -> tuple[int, object, float]:
        self.calls.append(
            {
                "actor": self.actor,
                "kind": "json",
                "method": method,
                "path": path,
                "payload": payload,
                "timeout": timeout,
            }
        )

        if path == "/api/v1/settings/status" and self.actor == "outsider":
            status = self.settings_statuses.pop(0)
            body: object = {} if status == 200 else {"detail": "forbidden"}
            return status, body, 0.01

        responses: dict[tuple[str, str], tuple[int, object]] = {
            ("GET", "/api/v1/settings/status"): (200, {}),
            ("GET", "/api/v1/groups/"): (200 if self.actor == "admin" else 403, {}),
            (
                "GET",
                "/api/v1/audit/access-graph/summary",
            ): (200 if self.actor == "admin" else 403, {}),
            (
                "GET",
                "/api/v1/audit/access-graph/export?export_format=json&limit=10",
            ): (200 if self.actor == "admin" else 403, {}),
            (
                "POST",
                "/api/v1/datasets/",
            ): (
                201,
                {
                    "id": "ds-1",
                    "dataset_id": "ds-ignored",
                },
            ),
            ("GET", "/api/v1/documents/doc-1"): (200, {"status": "completed"}),
            (
                "PUT",
                "/api/v1/documents/doc-1/access",
            ): (
                200 if self.actor == "admin" else 403,
                {
                    "mode": "partial_members" if self.actor == "admin" else "inherit",
                    "partial_member_list": ["demo"] if self.actor == "admin" else [],
                    "partial_group_list": [],
                },
            ),
            (
                "GET",
                "/api/v1/documents/doc-1/access",
            ): (
                200 if self.actor == "admin" else 403,
                {
                    "mode": "partial_members",
                    "partial_member_list": ["demo"],
                    "partial_group_list": [],
                }
                if self.actor == "admin"
                else {"detail": "forbidden"},
            ),
            (
                "POST",
                "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=1000",
            ): (200, {}),
            ("DELETE", "/api/v1/datasets/ds-1"): (204, None),
        }
        return (*responses[(method, path)], 0.01)

    def multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        timeout: int | None = None,
    ) -> tuple[int, object, float]:
        self.calls.append(
            {
                "actor": self.actor,
                "kind": "multipart",
                "method": method,
                "path": path,
                "fields": fields,
                "file_path": file_path,
                "timeout": timeout,
            }
        )
        status = self.upload_status
        body: object = {"id": "doc-1"} if status in {200, 201} else {"detail": "upload failed"}
        return status, body, 0.01


def test_main_success_preserves_defaults_requests_and_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    constructor_calls: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []
    force_calls: list[dict[str, object]] = []

    def _build_live_api(
        base_url: str,
        tenant_id: str,
        account_id: str,
        user_id: str,
        timeout: int,
    ) -> FakeLiveApi:
        constructor_calls.append(
            {
                "base_url": base_url,
                "tenant_id": tenant_id,
                "account_id": account_id,
                "user_id": user_id,
                "timeout": timeout,
            }
        )
        actor = "admin" if account_id == "demo" else "outsider"
        statuses = [200, 403] if actor == "outsider" else None
        return FakeLiveApi(actor, requests, settings_statuses=statuses)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", _build_live_api)
    monkeypatch.setattr(
        mod,
        "force_member_role_via_docker",
        lambda **kwargs: force_calls.append(kwargs) or (True, "normalized"),
    )
    monkeypatch.setattr(sys, "argv", ["remote_permission_matrix.py"])

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "permission-matrix" / fixed_run_id).resolve()
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert rc == 0
    assert constructor_calls == [
        {
            "base_url": "http://127.0.0.1:8000",
            "tenant_id": mod.DEFAULT_TENANT_ID,
            "account_id": "demo",
            "user_id": "demo",
            "timeout": 300,
        },
        {
            "base_url": "http://127.0.0.1:8000",
            "tenant_id": mod.DEFAULT_TENANT_ID,
            "account_id": "outsider",
            "user_id": "outsider",
            "timeout": 300,
        },
    ]
    assert force_calls == [
        {
            "tenant_id": mod.DEFAULT_TENANT_ID,
            "account_id": "outsider",
            "role": "viewer",
            "postgres_container": "docker-mimirq-postgres-1",
            "timeout": 60,
        }
    ]
    assert [(call["actor"], call["kind"], call["method"], call["path"]) for call in requests] == [
        ("admin", "json", "GET", "/api/v1/settings/status"),
        ("outsider", "json", "GET", "/api/v1/settings/status"),
        ("outsider", "json", "GET", "/api/v1/settings/status"),
        ("admin", "json", "GET", "/api/v1/groups/"),
        ("outsider", "json", "GET", "/api/v1/groups/"),
        ("admin", "json", "GET", "/api/v1/audit/access-graph/summary"),
        ("outsider", "json", "GET", "/api/v1/audit/access-graph/summary"),
        (
            "admin",
            "json",
            "GET",
            "/api/v1/audit/access-graph/export?export_format=json&limit=10",
        ),
        (
            "outsider",
            "json",
            "GET",
            "/api/v1/audit/access-graph/export?export_format=json&limit=10",
        ),
        ("admin", "json", "POST", "/api/v1/datasets/"),
        ("admin", "multipart", "POST", "/api/v1/documents/upload"),
        ("admin", "json", "GET", "/api/v1/documents/doc-1"),
        ("admin", "json", "PUT", "/api/v1/documents/doc-1/access"),
        ("admin", "json", "GET", "/api/v1/documents/doc-1/access"),
        ("outsider", "json", "GET", "/api/v1/documents/doc-1/access"),
        ("outsider", "json", "PUT", "/api/v1/documents/doc-1/access"),
        (
            "admin",
            "json",
            "POST",
            "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=1000",
        ),
        ("admin", "json", "DELETE", "/api/v1/datasets/ds-1"),
    ]

    create_dataset_call = requests[9]
    assert create_dataset_call["payload"] == {
        "name": f"Permission Matrix {fixed_run_id}",
        "description": "Admin/permission verification dataset",
        "permission": "all_team_members",
        "default_parser_backend": "basic",
        "default_chunk_strategy": "langchain_recursive",
    }

    upload_call = requests[10]
    assert upload_call["fields"] == {
        "dataset_id": "ds-1",
        "parser_backend": "basic",
        "chunk_strategy": "langchain_recursive",
        "governance_enabled": "true",
        "chunk_vector_enabled": "true",
        "bm25_index_enabled": "true",
        "kg_enabled": "false",
        "event_vector_enabled": "false",
        "entity_vector_enabled": "false",
    }
    assert upload_call["file_path"] == artifact_dir / "permission-fixture.md"

    assert requests[12]["payload"] == {
        "mode": "partial_members",
        "partial_member_list": ["demo"],
        "partial_group_list": [],
    }
    assert requests[15]["payload"] == {
        "mode": "inherit",
        "partial_member_list": [],
        "partial_group_list": [],
    }
    assert requests[16]["payload"] == {}

    assert output == {
        "ok": True,
        "artifact_dir": str(artifact_dir),
        "dataset_id": "ds-1",
        "document_id": "doc-1",
        "error": None,
    }
    assert report["ok"] is True
    assert report["artifact_dir"] == str(artifact_dir)
    assert report["base_url"] == "http://127.0.0.1:8000"
    assert report["dataset_id"] == "ds-1"
    assert report["document_id"] == "doc-1"
    assert report["document_access_admin"] == {
        "mode": "partial_members",
        "partial_member_list": ["demo"],
        "partial_group_list": [],
    }
    assert [step["name"] for step in report["steps"]] == [
        "settings_status_admin",
        "force_outsider_role",
        "settings_status_outsider",
        "groups_admin",
        "groups_outsider",
        "access_graph_summary_admin",
        "access_graph_summary_outsider",
        "access_graph_export_admin",
        "access_graph_export_outsider",
        "create_dataset",
        "upload_document",
        "poll_document",
        "document_access_put_admin",
        "document_access_get_admin",
        "document_access_get_outsider",
        "document_access_put_outsider",
        "cleanup_purge_dataset",
        "cleanup_delete_dataset",
    ]


def test_main_failure_preserves_non_cleanup_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    requests: list[dict[str, object]] = []

    def _build_live_api(
        _base_url: str,
        _tenant_id: str,
        account_id: str,
        _user_id: str,
        _timeout: int,
    ) -> FakeLiveApi:
        actor = "admin" if account_id == "demo" else "outsider"
        return FakeLiveApi(actor, requests, settings_statuses=[403], upload_status=500)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", _build_live_api)
    monkeypatch.setattr(sys, "argv", ["remote_permission_matrix.py"])

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "permission-matrix" / fixed_run_id).resolve()
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert rc == 1
    assert output == {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "dataset_id": "ds-1",
        "document_id": None,
        "error": 'upload failed: {"detail": "upload failed"}',
    }
    assert report["ok"] is False
    assert "dataset_id" not in report
    assert report["error"] == 'upload failed: {"detail": "upload failed"}'
    assert [step["name"] for step in report["steps"]] == [
        "settings_status_admin",
        "settings_status_outsider",
        "groups_admin",
        "groups_outsider",
        "access_graph_summary_admin",
        "access_graph_summary_outsider",
        "access_graph_export_admin",
        "access_graph_export_outsider",
        "create_dataset",
        "upload_document",
    ]
    assert not any("purge" in str(call["path"]) for call in requests)
    assert not any(call["method"] == "DELETE" and call["path"] == "/api/v1/datasets/ds-1" for call in requests)
