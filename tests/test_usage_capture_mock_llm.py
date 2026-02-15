import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.chat import chat as chat_endpoint
from app.core.config import settings
from app.core.database import get_db


class FakeDB:
    def add(self, _obj) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


def test_usage_capture_includes_usage_block_when_mock_llm_enabled(monkeypatch) -> None:
    app = FastAPI()
    app.post("/api/v1/chat")(chat_endpoint)

    app.dependency_overrides[get_db] = lambda: FakeDB()
    app.dependency_overrides[get_tenant_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_current_account_id] = lambda: "acct_123"

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False, raising=False)

    # Avoid real dataset membership/permission checks.
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None)

    # Avoid real LangGraph work.
    import app.rag.pipelines.langgraph as langgraph_mod

    monkeypatch.setattr(langgraph_mod, "build_rag_state", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        langgraph_mod.rag_workflow,
        "invoke",
        lambda *_args, **_kwargs: {"citations": [], "answer": "ok", "metrics": {}},
    )

    # Avoid TAG DB/LLM work.
    import app.services.chat_tag_service as chat_tag_service_mod

    monkeypatch.setattr(
        chat_tag_service_mod,
        "build_chat_tag_context_docs",
        lambda *_args, **_kwargs: ([], {"enabled": False, "used": False}),
    )

    client = TestClient(app)
    res = client.post(
        "/api/v1/chat",
        json={
            "message": "hello",
            "stream": False,
            "dataset_id": str(uuid.uuid4()),
            "rag_config": {"use_graph": True},
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()

    assert "usage" in body
    assert body["usage"]["source"] == "mock"
    assert body["usage"]["prompt_tokens"] == 0
    assert body["usage"]["completion_tokens"] == body["total_tokens"]
    assert body["usage"]["total_tokens"] == body["total_tokens"]
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "source"):
        assert key in body["usage"]
