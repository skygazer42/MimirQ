from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.chat_conversations import get_conversation_messages
from app.api.v1.documents import batch_delete_documents, list_documents
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


def test_documents_sort_validation() -> None:
    app = _build_app()
    app.get("/api/v1/documents/")(list_documents)
    client = TestClient(app)

    res = client.get("/api/v1/documents/", params={"order_by": "nope"})
    assert res.status_code == 422

    res = client.get("/api/v1/documents/", params={"order_dir": "sideways"})
    assert res.status_code == 422


def test_documents_batch_delete_body_validation() -> None:
    app = _build_app()
    app.post("/api/v1/documents/batch-delete")(batch_delete_documents)
    client = TestClient(app)

    res = client.post("/api/v1/documents/batch-delete", json={"document_ids": []})
    assert res.status_code == 422

    too_many = [str(uuid.uuid4()) for _ in range(201)]
    res = client.post("/api/v1/documents/batch-delete", json={"document_ids": too_many})
    assert res.status_code == 422


def test_chat_messages_paging_validation() -> None:
    app = _build_app()
    app.get("/api/v1/chat/conversations/{conversation_id}/messages")(get_conversation_messages)
    client = TestClient(app)

    res = client.get(f"/api/v1/chat/conversations/{uuid.uuid4()}/messages", params={"limit": 501})
    assert res.status_code == 422

    res = client.get(
        f"/api/v1/chat/conversations/{uuid.uuid4()}/messages",
        params={"limit": 10, "before": "not-a-uuid"},
    )
    assert res.status_code == 422
