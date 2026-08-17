import hashlib
import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentVersionDiff
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.tenant import Tenant, TenantMember


def _add_tenant_owner(db: Any, *, tenant_id: uuid.UUID, account_id: str) -> None:
    db.add(Tenant(id=tenant_id, name=f"tenant-{tenant_id}", status="active", plan="basic"))
    db.add(
        TenantMember(
            tenant_id=tenant_id,
            user_id=account_id,
            role="owner",
            is_active=True,
            is_current=True,
        )
    )


def _make_app(db, *, tenant_id: uuid.UUID, account_id: str) -> FastAPI:  # noqa: ANN001
    from app.api.v1.documents import diff_document_versions

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: account_id

    app.get("/api/v1/documents/{document_id}/versions/diff", response_model=DocumentVersionDiff)(diff_document_versions)
    return app


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def _add_chunk(  # noqa: ANN001
    db,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    pipeline_hash: str,
    chunk_index: int,
    content: str,
) -> None:
    db.add(
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=chunk_index,
            content=content,
            doc_metadata={
                "pipeline_hash": pipeline_hash,
                "doc_pipeline_key": f"{document_id}:{pipeline_hash}",
                "content_len": len(content),
                "content_hash": _sha256(content.strip()),
                "content_hash_algo": "sha256",
            },
        )
    )


def test_document_version_diff_counts(pg_session):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    account_id = "test-account"
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    _add_tenant_owner(pg_session, tenant_id=tenant_id, account_id=account_id)
    pg_session.add(
        Dataset(
            id=dataset_id,
            tenant_id=tenant_id,
            name="ds",
            description=None,
            permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            owner_id=account_id,
            dataset_metadata={},
        )
    )

    pg_session.add(
        DBDocument(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="doc.txt",
            file_type="txt",
            file_size=3,
            file_path="uploads/doc.txt",
            status="completed",
            processing_progress=100,
            chunk_count=0,
            total_characters=0,
            owner_id=account_id,
            access_mode=None,
            doc_metadata={
                "active_pipeline_hash": "v2",
                "pipeline_hash": "v2",
            },
        )
    )

    # v1: A, B, C
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v1", chunk_index=0, content="A")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v1", chunk_index=1, content="B")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v1", chunk_index=2, content="C")

    # v2: A, B, D, D
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=0, content="A")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=1, content="B")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=2, content="D")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=3, content="D")

    pg_session.commit()

    app = _make_app(pg_session, tenant_id=tenant_id, account_id=account_id)
    client = TestClient(app)

    res = client.get(f"/api/v1/documents/{document_id}/versions/diff?from=v1&to=v2")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("document_id") == str(document_id)
    assert body.get("from_pipeline_hash") == "v1"
    assert body.get("to_pipeline_hash") == "v2"

    assert body.get("from_chunk_count") == 3
    assert body.get("to_chunk_count") == 4
    assert body.get("unchanged_chunks") == 2
    assert body.get("added_chunks") == 2
    assert body.get("removed_chunks") == 1


def test_unassigned_document_version_diff_allows_readable_viewers(pg_session, monkeypatch):  # noqa: ANN001
    monkeypatch.delenv("ENV", raising=False)

    tenant_id = uuid.uuid4()
    owner_id = "owner-account"
    account_id = "viewer-account"
    document_id = uuid.uuid4()

    pg_session.add(
        DBDocument(
            id=document_id,
            tenant_id=tenant_id,
            dataset_id=None,
            filename="doc.txt",
            file_type="txt",
            file_size=3,
            file_path="uploads/doc.txt",
            status="completed",
            processing_progress=100,
            chunk_count=0,
            total_characters=0,
            owner_id=owner_id,
            access_mode="all_team_members",
            doc_metadata={
                "active_pipeline_hash": "v2",
                "pipeline_hash": "v2",
            },
        )
    )

    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v1", chunk_index=0, content="A")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=1, content="B")
    pg_session.commit()

    monkeypatch.setattr(
        "app.api.v1.document_versions.DatasetService.ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="viewer"),
    )

    app = _make_app(pg_session, tenant_id=tenant_id, account_id=account_id)
    client = TestClient(app)

    res = client.get(f"/api/v1/documents/{document_id}/versions/diff?from=v1&to=v2")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("document_id") == str(document_id)
    assert body.get("from_chunk_count") == 1
    assert body.get("to_chunk_count") == 1
