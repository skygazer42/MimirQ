
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail, DocumentVersionList
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk


def _make_app(db, *, tenant_id: uuid.UUID, account_id: str) -> FastAPI:  # noqa: ANN001
    from app.api.v1.documents import activate_document_version, delete_document_version, list_document_versions

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: account_id

    app.get("/api/v1/documents/{document_id}/versions", response_model=DocumentVersionList)(list_document_versions)
    app.post(
        "/api/v1/documents/{document_id}/versions/{pipeline_hash}/activate",
        response_model=DocumentDetail,
    )(activate_document_version)
    app.delete("/api/v1/documents/{document_id}/versions/{pipeline_hash}", status_code=204)(delete_document_version)
    return app


def _add_chunk(db, *, tenant_id: uuid.UUID, document_id: uuid.UUID, pipeline_hash: str, chunk_index: int, content: str) -> None:  # noqa: ANN001
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
            },
        )
    )


def test_document_versions_list_activate_delete(pg_session, monkeypatch):  # noqa: ANN001
    # Force dev-like behaviour for membership bootstrap.
    monkeypatch.delenv("ENV", raising=False)

    tenant_id = uuid.uuid4()
    account_id = "test-account"
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

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
            chunk_count=2,
            total_characters=0,
            owner_id=account_id,
            access_mode=None,
            doc_metadata={
                # Start with v1 active, v2 as the current pipeline hash.
                "active_pipeline_hash": "v1",
                "pipeline_hash": "v2",
            },
        )
    )

    # v1: 2 chunks
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v1", chunk_index=0, content="hello v1-0")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v1", chunk_index=1, content="hello v1-1")
    # v2: 3 chunks
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=0, content="hello v2-0")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=1, content="hello v2-1")
    _add_chunk(pg_session, tenant_id=tenant_id, document_id=document_id, pipeline_hash="v2", chunk_index=2, content="hello v2-2")

    pg_session.commit()

    app = _make_app(pg_session, tenant_id=tenant_id, account_id=account_id)
    client = TestClient(app)

    # List versions
    res = client.get(f"/api/v1/documents/{document_id}/versions")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("document_id") == str(document_id)
    assert body.get("active_pipeline_hash") == "v1"
    hashes = {it.get("pipeline_hash") for it in (body.get("items") or [])}
    assert hashes == {"v1", "v2"}
    active_item = next(it for it in body["items"] if it["pipeline_hash"] == "v1")
    assert active_item["active"] is True

    # Activate v2
    res = client.post(f"/api/v1/documents/{document_id}/versions/v2/activate")
    assert res.status_code == 200, res.text
    doc = res.json()
    assert (doc.get("metadata") or {}).get("active_pipeline_hash") == "v2"
    assert doc.get("chunk_count") == 3

    # Cannot delete active version (v2)
    res = client.delete(f"/api/v1/documents/{document_id}/versions/v2")
    assert res.status_code == 409, res.text

    # Delete non-active version (v1)
    res = client.delete(f"/api/v1/documents/{document_id}/versions/v1")
    assert res.status_code == 204, res.text

    # List again: only v2 remains
    res = client.get(f"/api/v1/documents/{document_id}/versions")
    assert res.status_code == 200, res.text
    body = res.json()
    hashes = {it.get("pipeline_hash") for it in (body.get("items") or [])}
    assert hashes == {"v2"}
    active_item = next(it for it in body["items"] if it["pipeline_hash"] == "v2")
    assert active_item["active"] is True

