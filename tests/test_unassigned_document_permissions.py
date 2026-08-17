import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.schemas.document import (
    DocumentAccessUpdateRequest,
    DocumentBatchMoveRequest,
    DocumentBatchUserMetadataPatchRequest,
    DocumentChunkCreateRequest,
    DocumentChunkUpdateRequest,
    DocumentPipelinePatchRequest,
    DocumentUserMetadataPatchRequest,
)
from app.api.schemas.qa import DocumentQAGenerateRequest
from app.api.v1 import document_mutations, document_processing, document_versions
from app.services import document_access_service


class _Query:
    def __init__(self, document) -> None:  # noqa: ANN001
        self._document = document

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._document

    def limit(self, _value):  # noqa: ANN001, ANN201
        return self

    def scalar(self):  # noqa: ANN201
        return 0

    def all(self) -> list[tuple]:
        return []

    def execution_options(self, **_kwargs):  # noqa: ANN003, ANN201
        return self

    def enable_eagerloads(self, _value):  # noqa: ANN001, ANN201
        return self


class _DB:
    def __init__(self, document) -> None:  # noqa: ANN001
        self.document = document
        self.commits = 0

    def query(self, *_models):  # noqa: ANN001, ANN201
        return _Query(self.document)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None


class _BatchQuery:
    def __init__(self, documents) -> None:  # noqa: ANN001
        self._documents = list(documents)

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._documents[0] if self._documents else None

    def all(self) -> list[object]:
        return list(self._documents)


class _BatchDB:
    def __init__(self, documents) -> None:  # noqa: ANN001
        self._documents = list(documents)
        self.commits = 0

    def query(self, *_models):  # noqa: ANN001, ANN201
        return _BatchQuery(self._documents)

    def commit(self) -> None:
        self.commits += 1


def _unassigned_document(
    *,
    owner_id: str = "owner-account",
    access_mode: str | None = None,
    status: str = "completed",
    file_path: str = "uploads/doc.txt",
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=None,
        owner_id=owner_id,
        access_mode=access_mode,
        status=status,
        file_path=file_path,
        file_type="txt",
        filename="doc.txt",
        processing_progress=0,
        current_stage="ready",
        failed_stage=None,
        error_code=None,
        next_retry_at=None,
        error_message=None,
        doc_metadata={},
        chunk_count=0,
        total_characters=0,
    )


def test_unassigned_document_readable_helper_denies_inherit_to_non_owner() -> None:
    document = _unassigned_document(access_mode=None)

    with pytest.raises(HTTPException) as exc_info:
        document_access_service.assert_document_readable_for_lifecycle(
            _DB(document),
            tenant_id=document.tenant_id,
            account_id="other-account",
            document=document,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == document_access_service.NO_DOCUMENT_ACCESS_DETAIL


def test_unassigned_document_writable_helper_requires_edit_role(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _unassigned_document(access_mode="all_team_members")

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="viewer"),
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        document_access_service.assert_document_writable_for_lifecycle(
            _DB(document),
            tenant_id=document.tenant_id,
            account_id="viewer-account",
            document=document,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == document_access_service.NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL


def test_unassigned_document_writable_helper_denies_non_owner_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _unassigned_document(access_mode="all_team_members")

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="editor"),
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        document_access_service.assert_document_writable_for_lifecycle(
            _DB(document),
            tenant_id=document.tenant_id,
            account_id="editor-account",
            document=document,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == document_access_service.NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL


def test_unassigned_document_writable_helper_allows_owner_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _unassigned_document(access_mode="all_team_members", owner_id="editor-account")

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="editor"),
        raising=True,
    )

    document_access_service.assert_document_writable_for_lifecycle(
        _DB(document),
        tenant_id=document.tenant_id,
        account_id="editor-account",
        document=document,
    )


def test_unassigned_document_writable_helper_allows_admin_override(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _unassigned_document(access_mode="only_me", owner_id="other-owner")

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="admin"),
        raising=True,
    )

    document_access_service.assert_document_writable_for_lifecycle(
        _DB(document),
        tenant_id=document.tenant_id,
        account_id="admin-account",
        document=document,
    )


def test_unassigned_document_writable_helper_requires_admin_when_owner_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _unassigned_document(access_mode="all_team_members", owner_id="")

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="editor"),
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        document_access_service.assert_document_writable_for_lifecycle(
            _DB(document),
            tenant_id=document.tenant_id,
            account_id="editor-account",
            document=document,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == document_access_service.NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL


def test_unassigned_document_writable_helper_allows_admin_when_owner_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _unassigned_document(access_mode="all_team_members", owner_id="")

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="owner"),
        raising=True,
    )

    document_access_service.assert_document_writable_for_lifecycle(
        _DB(document),
        tenant_id=document.tenant_id,
        account_id="owner-account",
        document=document,
    )


@pytest.mark.asyncio
async def test_unassigned_document_processing_and_mutation_writes_require_edit_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _unassigned_document(access_mode="all_team_members", status="processing")
    db = _DB(document)

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="viewer"),
        raising=True,
    )
    monkeypatch.setattr(
        document_processing._documents_module().DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="viewer"),
        raising=True,
    )
    monkeypatch.setattr(
        document_mutations._documents_module().DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="viewer"),
        raising=True,
    )

    with pytest.raises(HTTPException) as cancel_exc:
        await document_processing.cancel_document_processing(
            document_id=document.id,
            tenant_id=document.tenant_id,
            account_id="viewer-account",
            db=db,
        )
    assert cancel_exc.value.status_code == 403
    assert cancel_exc.value.detail == document_access_service.NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL

    with pytest.raises(HTTPException) as metadata_exc:
        document_mutations.patch_document_user_metadata(
            document_id=document.id,
            payload=DocumentUserMetadataPatchRequest(patch={"label": "value"}),
            tenant_id=document.tenant_id,
            account_id="viewer-account",
            db=db,
        )
    assert metadata_exc.value.status_code == 403
    assert metadata_exc.value.detail == document_access_service.NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL


def test_unassigned_document_versions_are_readable_but_not_writable_for_viewers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _unassigned_document(
        access_mode="all_team_members",
        owner_id="owner-account",
        status="completed",
    )
    document.doc_metadata = {"active_pipeline_hash": "v1", "pipeline_hash": "v2"}
    db = _DB(document)

    monkeypatch.setattr(
        document_versions.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="viewer"),
        raising=True,
    )

    listing = document_versions.list_document_versions(
        document_id=document.id,
        tenant_id=document.tenant_id,
        account_id="viewer-account",
        db=db,
    )
    assert listing["document_id"] == document.id
    assert listing["active_pipeline_hash"] == "v1"
    assert listing["items"] == []

    with pytest.raises(HTTPException) as activate_exc:
        document_versions.activate_document_version(
            document_id=document.id,
            pipeline_hash="v2",
            tenant_id=document.tenant_id,
            account_id="viewer-account",
            db=db,
        )
    assert activate_exc.value.status_code == 403
    assert activate_exc.value.detail == document_access_service.NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL

    with pytest.raises(HTTPException) as delete_exc:
        document_versions.delete_document_version(
            document_id=document.id,
            pipeline_hash="v1",
            tenant_id=document.tenant_id,
            account_id="viewer-account",
            db=db,
        )
    assert delete_exc.value.status_code == 403
    assert delete_exc.value.detail == document_access_service.NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL


@pytest.mark.asyncio
async def test_document_processing_endpoints_use_shared_unassigned_acl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    documents_module = document_processing._documents_module()
    document = _unassigned_document(
        access_mode="all_team_members", status="processing", file_path=str(tmp_path / "retry.txt")
    )
    Path(document.file_path).write_text("hello", encoding="utf-8")
    db = _DB(document)
    sentinel = HTTPException(status_code=403, detail="shared-write-policy")

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_readable_for_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HTTPException(status_code=403, detail="shared-read-policy")),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sentinel),
        raising=True,
    )

    with pytest.raises(HTTPException) as status_exc:
        document_processing.get_document_status(
            document_id=document.id,
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert status_exc.value.detail == "shared-read-policy"

    with pytest.raises(HTTPException) as cancel_exc:
        await document_processing.cancel_document_processing(
            document_id=document.id,
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert cancel_exc.value is sentinel

    document.status = "failed"
    with pytest.raises(HTTPException) as retry_exc:
        await document_processing.retry_document_processing(
            document_id=document.id,
            background_tasks=BackgroundTasks(),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert retry_exc.value is sentinel


def test_document_mutation_endpoints_use_shared_unassigned_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    documents_module = document_mutations._documents_module()
    document = _unassigned_document(access_mode="all_team_members")
    db = _DB(document)
    sentinel = HTTPException(status_code=403, detail="shared-write-policy")

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sentinel),
        raising=True,
    )

    with pytest.raises(HTTPException) as qa_exc:
        document_mutations.generate_document_qa(
            document_id=document.id,
            payload=DocumentQAGenerateRequest(num_pairs=1),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert qa_exc.value is sentinel

    with pytest.raises(HTTPException) as pipeline_exc:
        document_mutations.patch_document_pipeline(
            document_id=document.id,
            payload=DocumentPipelinePatchRequest(),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert pipeline_exc.value is sentinel

    with pytest.raises(HTTPException) as metadata_exc:
        document_mutations.patch_document_user_metadata(
            document_id=document.id,
            payload=DocumentUserMetadataPatchRequest(patch={"label": "value"}),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert metadata_exc.value is sentinel


def test_document_access_put_uses_shared_acl_management_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import document_access

    document = _unassigned_document(access_mode="all_team_members")
    db = _DB(document)
    sentinel = HTTPException(status_code=403, detail="shared-write-policy")

    monkeypatch.setattr(document_access.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        document_access,
        "assert_document_access_manageable",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sentinel),
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        document_access.put_document_access(
            document_id=document.id,
            payload=DocumentAccessUpdateRequest(mode="all_team_members"),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )

    assert exc_info.value is sentinel


def test_document_access_management_preserves_dataset_write_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = uuid.uuid4()
    document = _unassigned_document(access_mode="only_me", owner_id="other-owner")
    document.dataset_id = dataset_id
    dataset = SimpleNamespace(id=dataset_id, tenant_id=document.tenant_id)
    writable_calls: list[tuple[object, str]] = []

    monkeypatch.setattr(
        document_access_service.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: dataset,
        raising=True,
    )
    monkeypatch.setattr(
        document_access_service.DatasetService,
        "assert_dataset_writable",
        lambda _db, value, account_id: writable_calls.append((value, account_id)),
        raising=True,
    )
    monkeypatch.setattr(
        document_access_service,
        "assert_document_acl_readable",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("current ACL must not block ACL repair")),
        raising=True,
    )

    document_access_service.assert_document_access_manageable(
        _DB(document),
        tenant_id=document.tenant_id,
        account_id="dataset-editor",
        document=document,
    )

    assert writable_calls == [(dataset, "dataset-editor")]


def test_documents_chunk_write_helper_delegates_to_shared_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.documents as documents_module

    document = _unassigned_document(access_mode="all_team_members")
    sentinel = HTTPException(status_code=403, detail="shared-write-policy")

    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sentinel),
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        documents_module._assert_document_writable_for_chunk_ops(
            _DB(document),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            document=document,
        )

    assert exc_info.value is sentinel


def test_document_chunk_write_endpoints_use_shared_unassigned_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.documents as documents_module
    from app.api.v1 import document_chunks_write

    document = _unassigned_document(access_mode="all_team_members")
    db = _DB(document)
    sentinel = HTTPException(status_code=403, detail="shared-write-policy")

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_chunk_ops",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sentinel),
        raising=True,
    )

    with pytest.raises(HTTPException) as create_exc:
        document_chunks_write.create_document_chunk(
            document_id=document.id,
            payload=DocumentChunkCreateRequest(content="chunk"),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert create_exc.value is sentinel

    with pytest.raises(HTTPException) as patch_exc:
        document_chunks_write.patch_document_chunk(
            document_id=document.id,
            chunk_id=uuid.uuid4(),
            payload=DocumentChunkUpdateRequest(content="patched"),
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert patch_exc.value is sentinel

    with pytest.raises(HTTPException) as delete_exc:
        import asyncio

        asyncio.run(
            document_chunks_write.delete_document_chunk(
                document_id=document.id,
                chunk_id=uuid.uuid4(),
                tenant_id=document.tenant_id,
                account_id="acct-1",
                db=db,
            )
        )
    assert delete_exc.value is sentinel


def test_document_batch_mutations_use_shared_unassigned_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.documents as documents_module
    from app.api.v1 import document_batches

    document = _unassigned_document(access_mode="all_team_members")
    db = _BatchDB([document])
    sentinel = HTTPException(status_code=403, detail="shared-write-policy")

    monkeypatch.setattr(
        document_batches._documents_module().DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="editor"),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sentinel),
        raising=True,
    )

    metadata_result = document_batches.batch_patch_document_user_metadata(
        payload=DocumentBatchUserMetadataPatchRequest(document_ids=[document.id], patch={"label": "value"}),
        tenant_id=document.tenant_id,
        account_id="acct-1",
        db=db,
    )
    assert metadata_result["updated"] == 0
    assert metadata_result["denied"] == [document.id]

    move_result = document_batches.batch_move_documents(
        payload=DocumentBatchMoveRequest(document_ids=[document.id], target_dataset_id=None),
        tenant_id=document.tenant_id,
        account_id="acct-1",
        db=db,
    )
    assert move_result["moved"] == 0
    assert move_result["denied"] == [document.id]


def test_batch_move_to_unassigned_denies_non_owner_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.documents as documents_module
    from app.api.v1 import document_batches

    document = _unassigned_document(owner_id="other-owner", access_mode="all_team_members")
    document.dataset_id = uuid.uuid4()
    db = _BatchDB([document])

    monkeypatch.setattr(
        document_batches._documents_module().DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="editor"),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    move_result = document_batches.batch_move_documents(
        payload=DocumentBatchMoveRequest(document_ids=[document.id], target_dataset_id=None),
        tenant_id=document.tenant_id,
        account_id="editor-account",
        db=db,
    )

    assert move_result["moved"] == 0
    assert move_result["denied"] == [document.id]
    assert document.dataset_id is not None


def test_batch_move_to_unassigned_allows_owner_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.documents as documents_module
    from app.api.v1 import document_batches

    document = _unassigned_document(owner_id="editor-account", access_mode="all_team_members")
    original_dataset_id = uuid.uuid4()
    document.dataset_id = original_dataset_id
    db = _BatchDB([document])

    monkeypatch.setattr(
        document_batches._documents_module().DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="editor"),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    move_result = document_batches.batch_move_documents(
        payload=DocumentBatchMoveRequest(document_ids=[document.id], target_dataset_id=None),
        tenant_id=document.tenant_id,
        account_id="editor-account",
        db=db,
    )

    assert move_result["moved"] == 1
    assert move_result["denied"] == []
    assert document.dataset_id is None


def test_batch_move_to_unassigned_allows_admin_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.documents as documents_module
    from app.api.v1 import document_batches

    document = _unassigned_document(owner_id="other-owner", access_mode="only_me")
    original_dataset_id = uuid.uuid4()
    document.dataset_id = original_dataset_id
    db = _BatchDB([document])

    monkeypatch.setattr(
        document_batches._documents_module().DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="admin"),
        raising=True,
    )
    monkeypatch.setattr(
        documents_module,
        "_assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    move_result = document_batches.batch_move_documents(
        payload=DocumentBatchMoveRequest(document_ids=[document.id], target_dataset_id=None),
        tenant_id=document.tenant_id,
        account_id="admin-account",
        db=db,
    )

    assert move_result["moved"] == 1
    assert move_result["denied"] == []
    assert document.dataset_id is None


def test_document_version_endpoints_use_shared_unassigned_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _unassigned_document(access_mode="all_team_members")
    db = _DB(document)
    read_exc = HTTPException(status_code=403, detail="shared-read-policy")
    write_exc = HTTPException(status_code=403, detail="shared-write-policy")

    monkeypatch.setattr(document_versions.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        document_versions,
        "assert_document_readable_for_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(read_exc),
        raising=True,
    )
    monkeypatch.setattr(
        document_versions,
        "assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(write_exc),
        raising=True,
    )

    with pytest.raises(HTTPException) as list_exc:
        document_versions.list_document_versions(
            document_id=document.id,
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert list_exc.value is read_exc

    with pytest.raises(HTTPException) as diff_exc:
        document_versions.diff_document_versions(
            document_id=document.id,
            from_pipeline_hash="v1",
            to_pipeline_hash="v2",
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert diff_exc.value is read_exc

    with pytest.raises(HTTPException) as activate_exc:
        document_versions.activate_document_version(
            document_id=document.id,
            pipeline_hash="v2",
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert activate_exc.value is write_exc

    with pytest.raises(HTTPException) as delete_exc:
        document_versions.delete_document_version(
            document_id=document.id,
            pipeline_hash="v1",
            tenant_id=document.tenant_id,
            account_id="acct-1",
            db=db,
        )
    assert delete_exc.value is write_exc
