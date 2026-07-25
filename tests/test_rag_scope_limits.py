from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.api.v1.rag as rag_api
import app.services.document_access as document_access
import app.services.tenant_quota_service as tenant_quota_service
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.middleware.request_id import RequestIDMiddleware
from app.core.database import get_db
from app.core.exceptions import register_exception_handlers


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(rag_api.router, prefix="/api/v1/rag")
    app.dependency_overrides[get_current_account_id] = lambda: "acct-1"
    app.dependency_overrides[get_tenant_id] = lambda: uuid4()

    def _override_get_db():
        yield object()

    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.mark.parametrize("path", ["/api/v1/rag/retrieve-preview", "/api/v1/rag/retrieve"])
@pytest.mark.parametrize(
    ("field_name", "count"),
    [
        ("dataset_ids", rag_api.RETRIEVAL_SCOPE_MAX_DATASET_IDS + 1),
        ("document_ids", rag_api.RETRIEVAL_SCOPE_MAX_DOCUMENT_IDS + 1),
    ],
)
def test_retrieval_endpoints_reject_oversized_scope_lists(path: str, field_name: str, count: int) -> None:
    client = TestClient(_build_app())

    response = client.post(
        path,
        json={
            "query": "where is the service hall",
            field_name: [str(uuid4()) for _ in range(count)],
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "VALIDATION_ERROR"
    assert any(error.get("loc") == ["body", field_name] for error in payload["detail"]["errors"])


@pytest.mark.parametrize(("status_code", "detail"), [(403, "No dataset access"), (404, "Dataset not found")])
def test_retrieve_preview_preserves_dataset_acl_error_semantics(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    detail: str,
) -> None:
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)

    async def _fake_quota(**_kwargs):
        return {}

    def _deny_or_missing(*_args, **_kwargs):
        raise HTTPException(status_code=status_code, detail=detail)

    monkeypatch.setattr(tenant_quota_service, "enforce_tenant_qps_quota_async", _fake_quota, raising=True)
    monkeypatch.setattr(rag_api, "get_readable_datasets_map", _deny_or_missing, raising=True)

    client = TestClient(_build_app())
    response = client.post(
        "/api/v1/rag/retrieve-preview",
        json={"query": "where is the service hall", "dataset_ids": [str(uuid4())]},
    )

    assert response.status_code == status_code
    payload = response.json()
    assert payload["message"] == detail


def test_get_readable_datasets_map_distinguishes_missing_from_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    account_id = "acct-1"
    readable_dataset = uuid4()
    blocked_dataset = uuid4()
    missing_dataset = uuid4()

    monkeypatch.setattr(document_access.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        document_access,
        "_resolve_allowed_dataset_ids",
        lambda *_args, **_kwargs: (
            {
                readable_dataset: SimpleNamespace(id=readable_dataset),
                blocked_dataset: SimpleNamespace(id=blocked_dataset),
            },
            {readable_dataset},
        ),
        raising=True,
    )

    with pytest.raises(HTTPException) as missing_exc:
        document_access.get_readable_datasets_map(
            object(),
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_ids=[readable_dataset, missing_dataset],
        )
    assert missing_exc.value.status_code == 404
    assert missing_exc.value.detail == "Dataset not found"

    with pytest.raises(HTTPException) as blocked_exc:
        document_access.get_readable_datasets_map(
            object(),
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_ids=[readable_dataset, blocked_dataset],
        )
    assert blocked_exc.value.status_code == 403
    assert blocked_exc.value.detail == "No dataset access"


def test_assert_dataset_ids_readable_uses_batch_acl_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    dataset_ids = [uuid4(), uuid4()]
    seen: dict[str, object] = {}

    def _fake_get_readable_datasets_map(_db, tenant_id, account_id, dataset_ids, *, check_member):  # noqa: ANN001
        seen["tenant_id"] = tenant_id
        seen["account_id"] = account_id
        seen["dataset_ids"] = list(dataset_ids)
        seen["check_member"] = check_member
        return {dataset_id: object() for dataset_id in dataset_ids}

    monkeypatch.setattr(rag_api, "get_readable_datasets_map", _fake_get_readable_datasets_map, raising=True)
    monkeypatch.setattr(
        rag_api.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: pytest.fail("per-dataset get_dataset lookup should not run"),
        raising=True,
    )
    monkeypatch.setattr(
        rag_api.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: pytest.fail("per-dataset assert_dataset_readable should not run"),
        raising=True,
    )

    rag_api._assert_dataset_ids_readable(
        object(),
        tenant_id=tenant_id,
        account_id="acct-1",
        dataset_ids=dataset_ids,
    )

    assert seen == {
        "tenant_id": tenant_id,
        "account_id": "acct-1",
        "dataset_ids": dataset_ids,
        "check_member": False,
    }
