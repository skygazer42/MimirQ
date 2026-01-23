from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.documents import list_document_chunks, list_documents
from app.api.v1.parsing import list_parsing_documents
from app.core.database import get_db


class _DummyDB:
    def close(self) -> None:  # noqa: D401
        """No-op close."""
        return None

    def rollback(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    return app


def test_documents_list_limit_validation() -> None:
    app = _build_app()
    app.get("/api/v1/documents/")(list_documents)
    client = TestClient(app)

    res = client.get("/api/v1/documents/", params={"limit": 201})
    assert res.status_code == 422


def test_parsing_documents_list_limit_validation() -> None:
    app = _build_app()
    app.get("/api/v1/parsing/documents")(list_parsing_documents)
    client = TestClient(app)

    res = client.get("/api/v1/parsing/documents", params={"limit": 201})
    assert res.status_code == 422


def test_document_chunks_list_limit_validation() -> None:
    app = _build_app()
    app.get("/api/v1/documents/{document_id}/chunks")(list_document_chunks)
    client = TestClient(app)

    res = client.get(f"/api/v1/documents/{uuid.uuid4()}/chunks", params={"limit": 2001})
    assert res.status_code == 422

