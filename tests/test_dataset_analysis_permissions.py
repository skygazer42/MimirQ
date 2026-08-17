import datetime as _dt
from types import SimpleNamespace
from uuid import uuid4

import starlette.status as _status

if not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc
if not hasattr(_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _status.HTTP_413_CONTENT_TOO_LARGE = _status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
if not hasattr(_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _status.HTTP_422_UNPROCESSABLE_CONTENT = _status.HTTP_422_UNPROCESSABLE_ENTITY

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import dataset_analysis as dataset_analysis_api
from app.core.database import get_db
from app.core.exceptions import register_exception_handlers


def _build_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str, str]:
    tenant_id = str(uuid4())
    dataset_id = str(uuid4())

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(dataset_analysis_api.router, prefix="/api/v1/datasets")
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "reader-1"
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(dataset_analysis_api.DatasetService, "ensure_member", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService,
        "get_dataset",
        lambda *_a, **_k: SimpleNamespace(id=dataset_id, name="Dataset A"),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "build_dataset_analysis_summary",
        lambda **_k: {"ok": True},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "build_dataset_analysis_examples",
        lambda **_k: {"ok": True},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "build_dataset_analysis_rule_suggestions",
        lambda **_k: {"ok": True},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "export_dataset_analysis_json",
        lambda **_k: {"ok": True},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "export_dataset_analysis_jsonl",
        lambda **_k: '{"ok":true}\n',
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "export_dataset_analysis_html",
        lambda **_k: "<html></html>",
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "writeback_dataset_analysis_glossary_candidates",
        lambda **_k: {"ok": True},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "create_dataset_analysis_png_task",
        lambda **_k: {"task_id": "task-1", "status": "pending"},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "get_dataset_analysis_png_task_status",
        lambda **_k: {"task_id": "task-1", "status": "done"},
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api,
        "get_dataset_analysis_png_result",
        lambda **_k: b"\x89PNG\r\n\x1a\n",
        raising=True,
    )
    return TestClient(app), tenant_id, dataset_id


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/summary"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/examples"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/rule-suggestions?ruleset=core"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/export.json"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/export.jsonl"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/report.html"),
        ("POST", "/api/v1/datasets/{dataset_id}/analysis/export.png"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/export-tasks/task-1"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/export-tasks/task-1/result.png"),
    ],
)
def test_dataset_analysis_read_endpoints_require_dataset_readable(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    client, _tenant_id, dataset_id = _build_client(monkeypatch)
    readable_calls: list[tuple[str, str]] = []
    writable_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        dataset_analysis_api.DatasetService,
        "assert_dataset_readable",
        lambda _db, dataset, account_id: readable_calls.append((str(dataset.id), account_id)),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService,
        "assert_dataset_writable",
        lambda _db, dataset, account_id: writable_calls.append((str(dataset.id), account_id)),
        raising=True,
    )

    response = client.request(method, path.format(dataset_id=dataset_id))

    assert response.status_code in (200, 202)
    assert readable_calls == [(dataset_id, "reader-1")]
    assert writable_calls == []


def test_glossary_writeback_requires_dataset_writable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _tenant_id, dataset_id = _build_client(monkeypatch)
    readable_calls: list[tuple[str, str]] = []
    writable_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        dataset_analysis_api.DatasetService,
        "assert_dataset_readable",
        lambda _db, dataset, account_id: readable_calls.append((str(dataset.id), account_id)),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService,
        "assert_dataset_writable",
        lambda _db, dataset, account_id: writable_calls.append((str(dataset.id), account_id)),
        raising=True,
    )

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/analysis/glossary-writeback",
        params={"ruleset": "core"},
    )

    assert response.status_code == 200
    assert readable_calls == []
    assert writable_calls == [(dataset_id, "reader-1")]


@pytest.mark.parametrize(
    ("method", "path", "service_name"),
    [
        ("POST", "/api/v1/datasets/{dataset_id}/analysis/export.png", "create_dataset_analysis_png_task"),
        ("GET", "/api/v1/datasets/{dataset_id}/analysis/export-tasks/task-1", "get_dataset_analysis_png_task_status"),
        (
            "GET",
            "/api/v1/datasets/{dataset_id}/analysis/export-tasks/task-1/result.png",
            "get_dataset_analysis_png_result",
        ),
    ],
)
def test_png_task_endpoints_forward_current_account(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    service_name: str,
) -> None:
    client, _tenant_id, dataset_id = _build_client(monkeypatch)
    seen: list[str] = []

    monkeypatch.setattr(
        dataset_analysis_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True
    )

    def _capture(**kwargs):
        seen.append(str(kwargs["account_id"]))
        if service_name == "create_dataset_analysis_png_task":
            return {"task_id": "task-1", "status": "pending"}
        if service_name == "get_dataset_analysis_png_task_status":
            return {"task_id": "task-1", "status": "done"}
        return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr(dataset_analysis_api, service_name, _capture, raising=True)

    response = client.request(method, path.format(dataset_id=dataset_id))

    assert response.status_code in (200, 202)
    assert seen == ["reader-1"]
