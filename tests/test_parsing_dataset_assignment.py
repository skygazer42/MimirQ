import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile


class _CaptureQuery:
    def __init__(self, first_result=None) -> None:  # noqa: ANN001
        self.first_result = first_result
        self.filters: list[object] = []

    def filter(self, *criteria: object):  # noqa: ANN201
        self.filters.extend(criteria)
        return self

    def first(self):  # noqa: ANN201
        return self.first_result

    def count(self) -> int:
        return 0

    def order_by(self, *_args: object, **_kwargs: object):  # noqa: ANN201
        return self

    def offset(self, *_args: object, **_kwargs: object):  # noqa: ANN201
        return self

    def limit(self, *_args: object, **_kwargs: object):  # noqa: ANN201
        return self

    def all(self) -> list[object]:
        return []


class _CaptureDB:
    def __init__(self, *, first_result=None) -> None:  # noqa: ANN001
        self.query_obj = _CaptureQuery(first_result=first_result)
        self.added: list[object] = []
        self.commits = 0
        self.refreshed: list[object] = []

    def query(self, _model: object) -> _CaptureQuery:
        return self.query_obj

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)


def _upload_file(*, filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


@pytest.mark.asyncio
async def test_upload_parsing_document_persists_selected_dataset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import app.api.v1.parsing as parsing_module

    tenant_id = uuid.uuid4()
    target_dataset_id = uuid.uuid4()
    target_dataset = SimpleNamespace(id=target_dataset_id, name="Company KB")
    db = _CaptureDB()

    monkeypatch.setattr(parsing_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(parsing_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: target_dataset,
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module,
        "_get_or_create_workspace_dataset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("workspace dataset should not be used")),
        raising=True,
    )
    monkeypatch.setattr(parsing_module, "document_object_storage_enabled", lambda: False, raising=True)

    async def _save_upload_file(file: UploadFile, target_path: Path, max_bytes: int) -> int:  # noqa: ARG001
        data = await file.read()
        target_path.write_bytes(data)
        return len(data)

    monkeypatch.setattr(parsing_module, "save_upload_file", _save_upload_file, raising=True)

    result = await parsing_module.upload_parsing_document(
        file=_upload_file(filename="contract.pdf", content=b"%PDF-1.4\nbody\n"),
        parser_backend="auto",
        dataset_id=target_dataset_id,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result.dataset_id == target_dataset_id
    assert result.owner_id == "acct-1"
    assert result.doc_metadata["workspace"] == "parsing"
    assert result.doc_metadata["target_dataset_id"] == str(target_dataset_id)
    assert result.doc_metadata["target_dataset_name"] == "Company KB"
    assert Path(str(result.file_path)).exists()
    assert db.added == [result]
    assert db.commits == 1
    assert db.refreshed == [result]


@pytest.mark.asyncio
async def test_upload_parsing_document_uses_selected_dataset_for_object_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.api.v1.parsing as parsing_module

    tenant_id = uuid.uuid4()
    target_dataset_id = uuid.uuid4()
    target_dataset = SimpleNamespace(id=target_dataset_id, name="Company KB")
    db = _CaptureDB()
    upload_calls: list[dict[str, str]] = []

    class _Store:
        def upload_document_file(self, **kwargs: str) -> str:  # noqa: ANN003
            upload_calls.append(dict(kwargs))
            return "minio://bucket/doc.pdf"

    monkeypatch.setattr(parsing_module.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(parsing_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: target_dataset,
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module,
        "_get_or_create_workspace_dataset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("workspace dataset should not be used")),
        raising=True,
    )
    monkeypatch.setattr(parsing_module, "document_object_storage_enabled", lambda: True, raising=True)
    monkeypatch.setattr(parsing_module, "get_document_object_store", lambda: _Store(), raising=True)
    monkeypatch.setattr(parsing_module, "is_object_storage_uri", lambda value: str(value).startswith("minio://"), raising=True)
    monkeypatch.setattr(
        parsing_module,
        "document_object_store_metadata",
        lambda _store: {"source_storage_backend": "object_storage"},
        raising=True,
    )

    async def _save_upload_file(file: UploadFile, target_path: Path, max_bytes: int) -> int:  # noqa: ARG001
        data = await file.read()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return len(data)

    monkeypatch.setattr(parsing_module, "save_upload_file", _save_upload_file, raising=True)

    result = await parsing_module.upload_parsing_document(
        file=_upload_file(filename="contract.pdf", content=b"%PDF-1.4\nbody\n"),
        parser_backend="auto",
        dataset_id=target_dataset_id,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result.dataset_id == target_dataset_id
    assert result.file_path == "minio://bucket/doc.pdf"
    assert len(upload_calls) == 1
    upload_call = upload_calls[0]
    assert str(upload_call["file_path"]) == str(
        (tmp_path / str(tenant_id) / ".tmp" / f"{result.id}.pdf").resolve(strict=False)
    )
    assert upload_calls == [
        {
            "file_path": upload_call["file_path"],
            "tenant_id": str(tenant_id),
            "dataset_id": str(target_dataset_id),
            "document_id": str(result.id),
            "extension": ".pdf",
            "content_type": "application/octet-stream",
        }
    ]


def test_list_parsing_documents_default_scope_includes_owner_bound_company_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.parsing as parsing_module

    tenant_id = uuid.uuid4()
    workspace_dataset_id = uuid.uuid4()
    db = _CaptureDB()

    monkeypatch.setattr(
        parsing_module,
        "_get_or_create_workspace_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=workspace_dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    parsing_module.list_parsing_documents(
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    joined_filters = "\n".join(str(filter_expr) for filter_expr in db.query_obj.filters)
    assert "documents.owner_id" in joined_filters
    assert "documents.dataset_id" in joined_filters
    assert "target_dataset_id" not in joined_filters


def test_list_parsing_documents_dataset_filter_uses_real_dataset_with_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.parsing as parsing_module

    tenant_id = uuid.uuid4()
    workspace_dataset_id = uuid.uuid4()
    target_dataset_id = uuid.uuid4()
    db = _CaptureDB()

    monkeypatch.setattr(
        parsing_module,
        "_get_or_create_workspace_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=workspace_dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=target_dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    parsing_module.list_parsing_documents(
        dataset_id=target_dataset_id,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    joined_filters = "\n".join(str(filter_expr) for filter_expr in db.query_obj.filters)
    assert "documents.dataset_id" in joined_filters
    assert "documents.metadata" in joined_filters


def test_get_workspace_document_hides_owner_scoped_company_doc_from_other_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.parsing as parsing_module

    tenant_id = uuid.uuid4()
    target_dataset_id = uuid.uuid4()
    document = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=target_dataset_id,
        owner_id="owner-1",
        doc_metadata={"workspace": "parsing"},
    )
    db = _CaptureDB(first_result=document)

    monkeypatch.setattr(parsing_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=target_dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        parsing_module.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        parsing_module._get_workspace_document(
            db,
            tenant_id=tenant_id,
            account_id="other-user",
            document_id=document.id,
        )

    assert exc_info.value.status_code == 404
