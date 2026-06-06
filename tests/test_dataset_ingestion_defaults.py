from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def test_dataset_create_persists_and_normalizes_ingestion_defaults(monkeypatch):  # noqa: ANN001
    from app.api.schemas.dataset import DatasetCreate
    from app.api.v1.datasets import create_dataset
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.description = None
            self.permission = "all_team_members"
            self.owner_id = "test-account"
            self.dataset_metadata = {}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "create_dataset", lambda **_kwargs: ds, raising=True)

    out = create_dataset(
        payload=DatasetCreate(
            name="Demo",
            default_parser_backend="pymupdf",  # alias -> basic
            default_chunk_strategy="outline",
        ),
        tenant_id=tenant_id,
        account_id="test-account",
        db=_DummyDB(),
    )

    assert ds.dataset_metadata.get("default_parser_backend") == "basic"
    assert ds.dataset_metadata.get("default_chunk_strategy") == "outline"
    assert out.default_parser_backend == "basic"
    assert out.default_chunk_strategy == "outline"


def test_dataset_create_pipeline_response_ignores_internal_only_options(monkeypatch):  # noqa: ANN001
    from app.api.schemas.dataset import DatasetCreate
    from app.api.v1.datasets import create_dataset
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.description = None
            self.permission = "all_team_members"
            self.owner_id = "test-account"
            self.dataset_metadata = {
                "pipeline": {
                    "chunk_size": 512,
                    "index": {
                        "embedding_contextual_retrieval_enabled": True,
                        "embedding_contextual_retrieval_lazy_mode": True,
                    },
                    "images": {
                        "caption_enabled": True,
                        "ocr_enabled": True,
                        "ocr_max_chars": 1200,
                        "ocr_max_images": 8,
                    },
                }
            }

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "create_dataset", lambda **_kwargs: ds, raising=True)

    out = create_dataset(
        payload=DatasetCreate(name="Demo"),
        tenant_id=tenant_id,
        account_id="test-account",
        db=_DummyDB(),
    )

    assert out.pipeline is not None
    assert out.pipeline.chunk_size == 512
    assert out.pipeline.embedding_contextual_retrieval_enabled is True
    assert not hasattr(out.pipeline, "embedding_contextual_retrieval_lazy_mode")
    assert not hasattr(out.pipeline, "image_ocr_enabled")


def test_dataset_create_rejects_unknown_parser_backend(monkeypatch):  # noqa: ANN001
    from app.api.schemas.dataset import DatasetCreate
    from app.api.v1.datasets import create_dataset
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = uuid.uuid4()
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.description = None
            self.permission = "all_team_members"
            self.owner_id = "test-account"
            self.dataset_metadata = {}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "create_dataset", lambda **_kwargs: ds, raising=True)

    with pytest.raises(HTTPException) as exc:
        create_dataset(
            payload=DatasetCreate(
                name="Demo",
                default_parser_backend="not-a-backend",
            ),
            tenant_id=tenant_id,
            account_id="test-account",
            db=_DummyDB(),
        )
    assert exc.value.status_code == 400


def test_dataset_update_rejects_unknown_chunk_strategy(monkeypatch):  # noqa: ANN001
    from app.api.schemas.dataset import DatasetUpdate
    from app.api.v1.datasets import update_dataset
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.description = None
            self.permission = "all_team_members"
            self.owner_id = "test-account"
            self.dataset_metadata = {}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tid, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda _db, _dataset, _account_id: None, raising=True)
    monkeypatch.setattr(DatasetService, "update_dataset", lambda **_kwargs: ds, raising=True)

    with pytest.raises(HTTPException) as exc:
        update_dataset(
            dataset_id=dataset_id,
            payload=DatasetUpdate(default_chunk_strategy="not-a-strategy"),
            tenant_id=tenant_id,
            account_id="test-account",
            db=_DummyDB(),
        )
    assert exc.value.status_code == 400


def test_dataset_update_persists_embedding_defaults_as_dataset_metadata(monkeypatch):  # noqa: ANN001
    from app.api.schemas.dataset import DatasetEmbeddingDefaults, DatasetUpdate
    from app.api.v1.datasets import update_dataset
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.description = None
            self.permission = "all_team_members"
            self.owner_id = "test-account"
            self.dataset_metadata = {}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tid, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda _db, _dataset, _account_id: None, raising=True)
    monkeypatch.setattr(DatasetService, "update_dataset", lambda **_kwargs: ds, raising=True)

    out = update_dataset(
        dataset_id=dataset_id,
        payload=DatasetUpdate(
            embedding_defaults=DatasetEmbeddingDefaults(
                provider=" openai_compatible ",
                model=" bge-large-zh ",
                api_base=" https://example.test/v1 ",
            )
        ),
        tenant_id=tenant_id,
        account_id="test-account",
        db=_DummyDB(),
    )

    assert ds.dataset_metadata["embedding_defaults"] == {
        "provider": "openai_compatible",
        "model": "bge-large-zh",
        "api_base": "https://example.test/v1",
    }
    assert out.embedding_defaults is not None
    assert out.embedding_defaults.model == "bge-large-zh"


def test_dataset_update_can_clear_embedding_defaults_without_reingest(monkeypatch):  # noqa: ANN001
    from app.api.schemas.dataset import DatasetUpdate
    from app.api.v1.datasets import update_dataset
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.description = None
            self.permission = "all_team_members"
            self.owner_id = "test-account"
            self.dataset_metadata = {
                "embedding_defaults": {
                    "provider": "openai_compatible",
                    "model": "bge-large-zh",
                }
            }

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tid, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda _db, _dataset, _account_id: None, raising=True)
    monkeypatch.setattr(DatasetService, "update_dataset", lambda **_kwargs: ds, raising=True)

    out = update_dataset(
        dataset_id=dataset_id,
        payload=DatasetUpdate(embedding_defaults=None),
        tenant_id=tenant_id,
        account_id="test-account",
        db=_DummyDB(),
    )

    assert "embedding_defaults" not in ds.dataset_metadata
    assert out.embedding_defaults is None
