import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.remote_kb_permission_boundary as mod


def _successful_api_body(actor: str, method: str, path: str) -> dict[str, object]:
    if actor == "admin" and method == "GET" and path == "/api/v1/health":
        return {}
    if actor == "outsider" and method == "GET" and path == "/api/v1/datasets/?limit=1":
        return {}
    if actor == "admin" and method == "POST" and path == "/api/v1/groups/":
        return {"id": "group-1"}
    if actor == "admin" and method == "GET" and path == "/api/v1/groups/group-1/members?limit=50":
        return {"items": [{"user_id": "outsider"}]}
    if method == "PUT" and path == "/api/v1/documents/doc-private-acl/access":
        return {
            "mode": "partial_members",
            "partial_member_list": ["demo"],
            "partial_group_list": [],
        }
    if method == "PUT" and path == "/api/v1/documents/doc-group-acl/access":
        return {
            "mode": "partial_members",
            "partial_member_list": [],
            "partial_group_list": ["group-1"],
        }
    return {"citations": []}


class _SuccessfulApi:
    def __init__(self, actor: str, calls: list[tuple[str, str, str]]) -> None:
        self.actor = actor
        self.calls = calls

    def json(self, method: str, path: str, *, payload: dict | None = None) -> SimpleNamespace:
        self.calls.append((self.actor, method, path))
        return SimpleNamespace(
            status=200,
            body=_successful_api_body(self.actor, method, path),
            elapsed_sec=0.01,
        )


def test_document_access_summary_normalizes_acl_fields() -> None:
    assert mod.document_access_summary(None) == {
        "mode": "",
        "owner_id": None,
        "partial_member_list": [],
        "partial_group_list": [],
    }
    assert mod.document_access_summary(
        {
            "mode": " Partial_Members ",
            "owner_id": " owner-1 ",
            "partial_member_list": [" member-1 ", "", "member-2"],
            "partial_group_list": [" group-1 ", "", "group-2"],
        }
    ) == {
        "mode": "partial_members",
        "owner_id": "owner-1",
        "partial_member_list": ["member-1", "member-2"],
        "partial_group_list": ["group-1", "group-2"],
    }


def test_evaluate_http_expectation_reports_unexpected_status() -> None:
    assert mod.evaluate_http_expectation("inventory", 200, [200, 204]) == []
    assert mod.evaluate_http_expectation("inventory", 403, [200]) == ["inventory: expected_statuses=[200] actual=403"]


def _scenario_scope() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    datasets = {
        "shared": "ds-shared",
        "private": "ds-private",
        "group_shared": "ds-group",
        "doc_acl": "ds-doc-acl",
    }
    documents = {
        "shared": {"document_id": "doc-shared"},
        "private": {"document_id": "doc-private"},
        "group": {"document_id": "doc-group"},
        "doc_visible": {"document_id": "doc-visible"},
        "doc_private": {"document_id": "doc-private-acl"},
        "doc_group": {"document_id": "doc-group-acl"},
    }
    return datasets, documents


def test_inventory_checks_preserve_request_order_and_comparison_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    datasets, documents = _scenario_scope()
    calls: list[tuple[str, str]] = []
    exported_ids = iter(
        [
            ["doc-shared"],
            ["doc-group"],
            ["doc-group-acl", "doc-visible"],
        ]
    )

    class _Api:
        def json(self, method: str, path: str) -> SimpleNamespace:
            calls.append((method, path))
            status = 403 if "dataset_id=ds-private" in path else 200
            return SimpleNamespace(status=status, body={})

    monkeypatch.setattr(mod, "record_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "exported_document_ids", lambda _body: next(exported_ids))
    checks: list[dict[str, object]] = []

    mod.run_inventory_checks(
        _Api(),
        datasets=datasets,
        documents=documents,
        steps=[],
        http_checks=checks,
    )

    assert calls == [
        ("GET", "/api/v1/documents/?dataset_id=ds-shared&limit=20"),
        ("GET", "/api/v1/documents/?dataset_id=ds-private&limit=20"),
        ("GET", "/api/v1/documents/?dataset_id=ds-group&limit=20"),
        ("GET", "/api/v1/documents/?dataset_id=ds-doc-acl&limit=20"),
    ]
    assert [check["name"] for check in checks] == [
        "outsider_shared_inventory",
        "outsider_private_inventory",
        "outsider_group_inventory",
        "outsider_doc_acl_inventory",
    ]
    assert all(check["ok"] is True for check in checks)


def test_retrieve_and_chat_checks_preserve_scenario_order_and_payload_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    datasets, documents = _scenario_scope()
    calls: list[tuple[str, str, dict[str, object]]] = []

    class _Api:
        def __init__(self, actor: str) -> None:
            self.actor = actor

        def json(self, method: str, path: str, *, payload: dict[str, object]) -> SimpleNamespace:
            calls.append((self.actor, path, payload))
            is_private_dataset = payload.get("dataset_id") == datasets["private"]
            is_private_document = payload.get("document_ids") == [documents["doc_private"]["document_id"]]
            status = 403 if self.actor == "outsider" and (is_private_dataset or is_private_document) else 200
            return SimpleNamespace(status=status, body={"citations": []})

    monkeypatch.setattr(mod, "record_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "evaluate_permission_scope_case", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mod, "citation_document_ids", lambda _body: [])
    monkeypatch.setattr(mod, "response_text_from_body", lambda _body: "")
    rag_config = mod.build_rag_config()
    summary: dict[str, list[dict[str, object]]] = {
        "http_checks": [],
        "retrieve_checks": [],
        "chat_checks": [],
    }

    mod.run_retrieve_checks(
        _Api("admin"),
        _Api("outsider"),
        datasets=datasets,
        documents=documents,
        rag_config=rag_config,
        steps=[],
        summary=summary,
    )
    mod.run_chat_checks(
        _Api("outsider"),
        datasets=datasets,
        documents=documents,
        rag_config=rag_config,
        steps=[],
        chat_checks=summary["chat_checks"],
    )

    assert [check["name"] for check in summary["http_checks"]] == ["admin_private_retrieve"]
    assert [check["name"] for check in summary["retrieve_checks"]] == [
        "outsider_shared_retrieve",
        "outsider_group_retrieve",
        "outsider_private_retrieve",
        "outsider_mixed_scope_retrieve",
        "outsider_group_mixed_scope_retrieve",
        "outsider_doc_acl_visible_retrieve",
        "outsider_doc_acl_group_retrieve",
        "outsider_doc_acl_private_retrieve",
        "outsider_doc_acl_visible_mixed_scope_retrieve",
        "outsider_doc_acl_group_mixed_scope_retrieve",
        "outsider_doc_acl_private_direct_retrieve",
    ]
    assert [check["name"] for check in summary["chat_checks"]] == [
        "outsider_shared_chat",
        "outsider_group_chat",
        "outsider_private_chat",
        "outsider_mixed_scope_chat",
        "outsider_group_mixed_scope_chat",
        "outsider_doc_acl_visible_chat",
        "outsider_doc_acl_group_chat",
        "outsider_doc_acl_private_chat",
        "outsider_doc_acl_visible_mixed_scope_chat",
        "outsider_doc_acl_group_mixed_scope_chat",
        "outsider_doc_acl_private_direct_chat",
    ]
    assert [path for _, path, _ in calls[:12]] == ["/api/v1/rag/retrieve-preview"] * 12
    assert [path for _, path, _ in calls[12:]] == ["/api/v1/chat"] * 11
    assert calls[0][2]["dataset_id"] == "ds-private"
    assert calls[4][2]["document_ids"] == ["doc-shared", "doc-private"]
    assert calls[-1][2]["document_ids"] == ["doc-private-acl"]
    assert calls[12][2]["rag_config"] == {**rag_config, "answer_mode": "extractive", "max_tokens": 300}


@pytest.fixture
def fixed_run_id(monkeypatch: pytest.MonkeyPatch) -> str:
    run_id = "20260816-010203"
    monkeypatch.setattr(mod.time, "strftime", lambda _fmt: run_id)
    return run_id


def test_main_success_writes_report_and_preserves_summary_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    create_calls: list[dict[str, object]] = []
    upload_calls: list[dict[str, object]] = []
    cleanup_calls: list[str] = []
    json_calls: list[tuple[str, str, str]] = []
    export_ids = iter(
        [
            ["doc-shared"],
            ["doc-group"],
            ["doc-visible", "doc-group-acl"],
        ]
    )

    def _fixture(path: str, text: str) -> Path:
        file_path = tmp_path / "fixtures" / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text, encoding="utf-8")
        return file_path

    fixture_map = {
        "alpha-handbook.md": _fixture("alpha-handbook.md", "alpha"),
        "beta-runbook.md": _fixture("beta-runbook.md", "beta"),
    }
    (artifact_dir := tmp_path / "artifacts" / "fixtures").mkdir(parents=True, exist_ok=True)

    def _live_api(
        _base_url: str,
        _tenant_id: str,
        account_id: str,
        _user_id: str,
        _timeout: int,
    ) -> _SuccessfulApi:
        return _SuccessfulApi("admin" if account_id == "demo" else "outsider", json_calls)

    def _create_dataset(
        _api: object,
        *,
        steps: list[dict[str, object]],
        name: str,
        permission: str,
        partial_member_list: list[str] | None = None,
    ) -> str:
        dataset_id = {
            "KB Perm Shared 20260816-010203": "ds-shared",
            "KB Perm Group 20260816-010203": "ds-group",
            "KB Perm Doc ACL 20260816-010203": "ds-doc-acl",
            "KB Perm Private 20260816-010203": "ds-private",
        }[name]
        create_calls.append(
            {
                "name": name,
                "permission": permission,
                "partial_member_list": partial_member_list,
                "steps": steps,
            }
        )
        return dataset_id

    def _upload_fixture(
        _api: object,
        *,
        steps: list[dict[str, object]],
        dataset_id: str,
        label: str,
        file_path: Path,
        poll_timeout: int,
    ) -> dict[str, object]:
        documents = {
            "shared_alpha": {"document_id": "doc-shared", "status": "completed", "chunk_count": 1, "parsed_chars": 10},
            "private_beta": {"document_id": "doc-private", "status": "completed", "chunk_count": 1, "parsed_chars": 11},
            "group_shared": {"document_id": "doc-group", "status": "completed", "chunk_count": 1, "parsed_chars": 12},
            "doc_acl_visible": {
                "document_id": "doc-visible",
                "status": "completed",
                "chunk_count": 1,
                "parsed_chars": 13,
            },
            "doc_acl_private": {
                "document_id": "doc-private-acl",
                "status": "completed",
                "chunk_count": 1,
                "parsed_chars": 14,
            },
            "doc_acl_group": {
                "document_id": "doc-group-acl",
                "status": "completed",
                "chunk_count": 1,
                "parsed_chars": 15,
            },
        }
        upload_calls.append(
            {
                "dataset_id": dataset_id,
                "label": label,
                "file_name": file_path.name,
                "poll_timeout": poll_timeout,
                "steps": steps,
            }
        )
        return documents[label]

    monkeypatch.setattr(mod, "build_live_api", _live_api)
    monkeypatch.setattr(mod, "make_fixture_files", lambda path: fixture_map)
    monkeypatch.setattr(mod, "force_member_role_via_docker", lambda **_kwargs: (True, "normalized"))
    monkeypatch.setattr(mod, "create_dataset", _create_dataset)
    monkeypatch.setattr(mod, "upload_fixture", _upload_fixture)
    monkeypatch.setattr(
        mod,
        "cleanup_dataset",
        lambda _api, *, steps, dataset_id: cleanup_calls.append(dataset_id) or {"dataset_id": dataset_id},
    )
    monkeypatch.setattr(mod, "evaluate_http_expectation", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mod, "evaluate_permission_scope_case", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mod, "citation_document_ids", lambda _body: [])
    monkeypatch.setattr(mod, "response_text_from_body", lambda _body: "")
    monkeypatch.setattr(mod, "exported_document_ids", lambda _body: next(export_ids))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "remote_kb_permission_boundary.py",
            "--artifact-dir",
            str(artifact_dir.parent),
            "--poll-timeout",
            "77",
        ],
    )

    rc = mod.main()

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir.parent / "report.json").read_text(encoding="utf-8"))

    assert output["ok"] is True
    assert output["artifact_dir"] == str(artifact_dir.parent.resolve())
    assert output["group"] == {"group_id": "group-1", "member_ids": ["outsider"]}
    assert output["datasets"]["shared"]["dataset_id"] == "ds-shared"
    assert output["datasets"]["doc_acl"]["private_document_id"] == "doc-private-acl"
    assert output["cleanup"]["group"]["delete_group_status"] == 200
    assert report["summary"] == output
    assert isinstance(report["steps"], list)
    assert [call["name"] for call in create_calls] == [
        f"KB Perm Shared {fixed_run_id}",
        f"KB Perm Group {fixed_run_id}",
        f"KB Perm Doc ACL {fixed_run_id}",
        f"KB Perm Private {fixed_run_id}",
    ]
    assert [call["label"] for call in upload_calls] == [
        "shared_alpha",
        "private_beta",
        "group_shared",
        "doc_acl_visible",
        "doc_acl_private",
        "doc_acl_group",
    ]
    assert cleanup_calls == ["ds-shared", "ds-group", "ds-doc-acl", "ds-private"]
    assert json_calls[:5] == [
        ("admin", "GET", "/api/v1/health"),
        ("outsider", "GET", "/api/v1/datasets/?limit=1"),
        ("admin", "POST", "/api/v1/groups/"),
        ("admin", "POST", "/api/v1/groups/group-1/members"),
        ("admin", "GET", "/api/v1/groups/group-1/members?limit=50"),
    ]


def test_main_returns_nonzero_when_role_normalization_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    json_calls: list[tuple[str, str, str]] = []

    class _FakeApi:
        def __init__(self, actor: str) -> None:
            self.actor = actor

        def json(self, method: str, path: str, *, payload: dict | None = None) -> SimpleNamespace:
            json_calls.append((self.actor, method, path))
            return SimpleNamespace(status=200, body={}, elapsed_sec=0.01)

    def _live_api(
        _base_url: str,
        _tenant_id: str,
        account_id: str,
        _user_id: str,
        _timeout: int,
    ) -> _FakeApi:
        return _FakeApi("admin" if account_id == "demo" else "outsider")

    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setattr(mod, "build_live_api", _live_api)
    monkeypatch.setattr(
        mod,
        "make_fixture_files",
        lambda path: {
            "alpha-handbook.md": (path / "alpha-handbook.md"),
            "beta-runbook.md": (path / "beta-runbook.md"),
        },
    )
    monkeypatch.setattr(
        mod,
        "force_member_role_via_docker",
        lambda **_kwargs: (False, "psql denied"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["remote_kb_permission_boundary.py", "--artifact-dir", str(artifact_dir)],
    )

    rc = mod.main()

    assert rc == 1
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert output["ok"] is False
    assert output["normalization"] == {
        "viewer_role_forced": False,
        "detail": "psql denied",
    }
    assert "failed to normalize outsider role: psql denied" == output["error"]
    assert "cleanup" not in output
    assert report["summary"] == output
    assert isinstance(report["steps"], list)
    assert json_calls == [
        ("admin", "GET", "/api/v1/health"),
        ("outsider", "GET", "/api/v1/datasets/?limit=1"),
    ]
