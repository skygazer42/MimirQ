from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _FakeDB:
    """Minimal DB stub for chat endpoint scope tests (no real SQLAlchemy engine)."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


def _override_get_db():  # noqa: ANN001
    def _gen():  # noqa: ANN202
        yield _FakeDB()

    return _gen


def _install_chat_routes(app: FastAPI):  # noqa: ANN001
    from app.api.v1.chat import chat as chat_endpoint
    from app.api.v1.chat import stream_chat as stream_chat_endpoint

    app.post("/api/v1/chat")(chat_endpoint)
    app.post("/api/v1/chat/stream")(stream_chat_endpoint)


def _stub_graph(monkeypatch):  # noqa: ANN001
    """
    Prevent chat endpoints from hitting real retrieval/LLM code when scope is open.

    Our assertions are about status codes (400 vs 200), not model behavior.
    """
    import app.rag.pipelines.langgraph as lg_mod

    def _fake_invoke(state, config=None, context=None):  # noqa: ANN001
        return {"citations": [], "answer": "ok", "metrics": {}}

    def _fake_stream(state, config=None, context=None, stream_mode=None):  # noqa: ANN001
        yield "values", {"citations": [], "answer": "ok", "metrics": {}}

    monkeypatch.setattr(lg_mod.rag_workflow, "invoke", _fake_invoke, raising=False)
    monkeypatch.setattr(lg_mod.rag_workflow, "stream", _fake_stream, raising=False)

    # Avoid TAG DB/LLM work.
    import app.services.chat_tag_service as tag_mod

    def _fake_build_chat_tag_context_docs(db, *, tenant_id, document_ids, question):  # noqa: ANN001
        return [], {"enabled": False, "used": False, "reason": "stub", "returned": 0}

    monkeypatch.setattr(tag_mod, "build_chat_tag_context_docs", _fake_build_chat_tag_context_docs, raising=True)


def test_chat_requires_dataset_id_or_document_ids(monkeypatch):  # noqa: ANN001
    """
    Enterprise mode: disable tenant-level open-scope retrieval for chat.

    When neither dataset_id nor document_ids is provided, API should reject the request.
    """
    _stub_graph(monkeypatch)

    tenant_id = uuid.uuid4()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db()
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    _install_chat_routes(app)

    client = TestClient(app)
    res = client.post(
        "/api/v1/chat",
        json={
            "message": "hi",
            "stream": False,
            "rag_config": {"use_graph": True},
        },
    )
    assert res.status_code == 400


def test_stream_chat_requires_dataset_id_or_document_ids(monkeypatch):  # noqa: ANN001
    _stub_graph(monkeypatch)

    tenant_id = uuid.uuid4()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db()
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    _install_chat_routes(app)

    client = TestClient(app)
    res = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "hi",
            "rag_config": {"use_graph": True},
        },
    )
    assert res.status_code == 400

