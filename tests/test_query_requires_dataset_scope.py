import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.rag import retrieve_evidence as retrieve_endpoint
from app.core.config import settings
from app.core.database import get_db


class FakeDB:
    pass


def _build_test_client(monkeypatch, *, allow_open_scope: bool) -> TestClient:
    app = FastAPI()
    app.post("/api/v1/rag/retrieve")(retrieve_endpoint)

    app.dependency_overrides[get_db] = lambda: FakeDB()
    app.dependency_overrides[get_tenant_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_current_account_id] = lambda: "acct_123"

    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", allow_open_scope, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)

    # Avoid real dataset membership/permission checks.
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None)

    # Avoid real retrieval work (vector store, Postgres, etc).
    import app.rag.pipelines.langgraph as langgraph_mod

    monkeypatch.setattr(langgraph_mod, "build_rag_state", lambda *_args, **_kwargs: {})

    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod,
        "run_retrieval",
        lambda *_args, **_kwargs: {"citations": [], "metrics": {}, "query_for_retrieval": "q"},
        raising=True,
    )

    return TestClient(app)


def test_rag_retrieve_rejects_open_scope_when_flag_disabled(monkeypatch) -> None:
    client = _build_test_client(monkeypatch, allow_open_scope=False)
    res = client.post("/api/v1/rag/retrieve", json={"query": "hello"})

    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "dataset_id is required when document_ids is empty"


def test_rag_retrieve_allows_open_scope_when_flag_enabled(monkeypatch) -> None:
    client = _build_test_client(monkeypatch, allow_open_scope=True)
    res = client.post("/api/v1/rag/retrieve", json={"query": "hello"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["query_for_retrieval"] == "q"
    assert body["citations"] == []
