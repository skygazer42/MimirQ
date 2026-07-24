from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


def test_dataset_embedding_defaults_reject_non_milvus_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.schemas.dataset import DatasetEmbeddingDefaults
    from app.api.v1 import datasets

    monkeypatch.setattr(datasets.settings, "VECTOR_BACKEND", "faiss", raising=False)
    metadata: dict[str, object] = {}

    with pytest.raises(HTTPException) as exc_info:
        datasets._upsert_dataset_embedding_defaults_metadata(
            metadata,
            defaults=DatasetEmbeddingDefaults(provider="local", model="embed-a"),
        )

    assert exc_info.value.status_code == 400
    assert "VECTOR_BACKEND=milvus" in str(exc_info.value.detail)
    assert metadata == {}


def test_create_dataset_rejects_invalid_embedding_defaults_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.dataset import DatasetCreate, DatasetEmbeddingDefaults
    from app.api.v1 import datasets

    called = False

    def _create_dataset(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal called
        called = True
        raise AssertionError("service should not be called")

    monkeypatch.setattr(datasets.settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(datasets.DatasetService, "ensure_member", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(datasets.DatasetService, "_assert_edit_role", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(datasets.DatasetService, "create_dataset", _create_dataset, raising=True)

    with pytest.raises(HTTPException, match="VECTOR_BACKEND=milvus"):
        datasets.create_dataset(
            DatasetCreate(
                name="demo",
                embedding_defaults=DatasetEmbeddingDefaults(provider="local", model="embed-a"),
            ),
            tenant_id=uuid4(),
            account_id="owner-1",
            db=SimpleNamespace(),
        )

    assert called is False


def test_create_checks_membership_before_embedding_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.schemas.dataset import DatasetCreate, DatasetEmbeddingDefaults
    from app.api.v1 import datasets

    monkeypatch.setattr(datasets.settings, "VECTOR_BACKEND", "faiss", raising=False)

    def _deny(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise HTTPException(status_code=403, detail="Not a tenant member")

    monkeypatch.setattr(datasets.DatasetService, "ensure_member", _deny, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        datasets.create_dataset(
            DatasetCreate(
                name="denied",
                embedding_defaults=DatasetEmbeddingDefaults(provider="local", model="embed-a"),
            ),
            tenant_id=uuid4(),
            account_id="outsider",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 403


def test_clone_dataset_drops_invalid_embedding_defaults_on_non_milvus_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.dataset import DatasetCloneRequest
    from app.api.v1 import datasets
    from app.models.dataset import DatasetPermissionEnum

    tenant_id = uuid4()
    source_dataset = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        name="source",
        description=None,
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id="owner-1",
        dataset_metadata={"embedding_defaults": {"provider": "local", "model": "embed-a"}},
    )
    created_dataset = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        name="clone",
        description=None,
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id="owner-1",
        dataset_metadata={},
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(datasets.settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(datasets.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(datasets.DatasetService, "get_dataset", lambda *_a, **_k: source_dataset, raising=True)
    monkeypatch.setattr(datasets.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    def _create_dataset(**kwargs):  # noqa: ANN003, ANN202
        captured["dataset_metadata"] = kwargs.get("dataset_metadata")
        return created_dataset

    monkeypatch.setattr(datasets.DatasetService, "create_dataset", _create_dataset, raising=True)
    monkeypatch.setattr(datasets, "_dataset_out", lambda *_a, **_k: created_dataset, raising=True)
    monkeypatch.setattr(datasets, "audit_log_event", lambda *_a, **_k: None, raising=True)

    response = datasets.clone_dataset(
        source_dataset.id,
        DatasetCloneRequest(name="clone"),
        tenant_id=tenant_id,
        account_id="owner-1",
        db=SimpleNamespace(commit=lambda: None),
    )

    assert response is created_dataset
    assert captured["dataset_metadata"] == {}
def test_update_rejects_invalid_embedding_before_dataset_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.schemas.dataset import DatasetEmbeddingDefaults, DatasetUpdate
    from app.api.v1 import datasets

    monkeypatch.setattr(datasets.settings, "VECTOR_BACKEND", "faiss", raising=False)
    dataset = SimpleNamespace(dataset_metadata={})
    monkeypatch.setattr(datasets.DatasetService, "get_dataset", lambda *_a, **_k: dataset, raising=True)
    monkeypatch.setattr(datasets.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    called = False

    def _update_dataset(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(datasets.DatasetService, "update_dataset", _update_dataset, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        datasets.update_dataset(
            uuid4(),
            DatasetUpdate(
                embedding_defaults=DatasetEmbeddingDefaults(provider="local", model="embed-a")
            ),
            tenant_id=uuid4(),
            account_id="owner-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert called is False
