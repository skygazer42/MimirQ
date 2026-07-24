import json
import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


class _ConversationQuery:
    def __init__(self, conversation) -> None:  # noqa: ANN001
        self._conversation = conversation

    def filter(self, *_args, **_kwargs):  # noqa: ANN002,ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._conversation


class _ConversationDB:
    def __init__(self, conversation) -> None:  # noqa: ANN001
        self._conversation = conversation

    def query(self, *_args, **_kwargs):  # noqa: ANN002,ANN003
        return _ConversationQuery(self._conversation)


def test_answer_lineage_request_id_is_tenant_scoped(monkeypatch, tmp_path):  # noqa: ANN001
    from app.api.v1.lineage import get_answer_lineage
    from app.core.config import settings

    owner_tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    request_id = "req-cross-tenant"
    metrics_path = tmp_path / "rag_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "event": "rag_trace",
                "tenant_id": str(owner_tenant_id),
                "account_id": "acct-1",
                "request_id": request_id,
                "conversation_id": str(uuid.uuid4()),
                "citations": [],
                "retrieval": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "ENABLE_METRICS_LOG", True, raising=False)
    monkeypatch.setattr(settings, "METRICS_LOG_PATH", str(metrics_path), raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: other_tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "acct-1"
    app.get("/api/v1/lineage/answer/{request_id}")(get_answer_lineage)

    client = TestClient(app)
    response = client.get(f"/api/v1/lineage/answer/{request_id}")

    assert response.status_code == 404


def test_authorize_answer_lineage_access_allows_same_account_member(monkeypatch):  # noqa: ANN001
    import app.services.lineage_service as lineage_service

    tenant_id = uuid.uuid4()
    account_id = "acct-1"
    trace_record = {"tenant_id": str(tenant_id), "account_id": account_id, "request_id": "req-1"}

    monkeypatch.setattr(
        lineage_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )

    assert (
        lineage_service.authorize_answer_lineage_access(
            _DummyDB(),
            tenant_id=tenant_id,
            account_id=account_id,
            trace_record=trace_record,
        )
        is True
    )


def test_chunk_lineage_requires_document_acl_when_not_observability_admin(monkeypatch):  # noqa: ANN001
    import app.api.v1.lineage as lineage_api
    import app.services.lineage_service as lineage_service

    tenant_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    document_id = uuid.uuid4()
    account_id = "acct-2"
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        lineage_api,
        "_load_chunk_lineage_dependencies",
        lambda *_args, **_kwargs: {
            "chunk": SimpleNamespace(id=chunk_id, document_id=document_id),
            "document": SimpleNamespace(id=document_id),
            "permissions": [],
            "retrieval_usage": {},
        },
        raising=True,
    )
    monkeypatch.setattr(
        lineage_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )

    def _deny_acl(db, requested_tenant_id, requested_account_id, doc_ids, **_kwargs):  # noqa: ANN001
        observed["tenant_id"] = requested_tenant_id
        observed["account_id"] = requested_account_id
        observed["doc_ids"] = list(doc_ids)
        return set(), set()

    monkeypatch.setattr(lineage_service, "get_allowed_document_id_sets", _deny_acl, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: account_id
    app.get("/api/v1/lineage/chunk/{chunk_id}")(lineage_api.get_chunk_lineage)

    client = TestClient(app)
    response = client.get(f"/api/v1/lineage/chunk/{chunk_id}")

    assert response.status_code == 404
    assert observed == {
        "tenant_id": tenant_id,
        "account_id": account_id,
        "doc_ids": [document_id],
    }


def test_answer_lineage_forbidden_when_one_citation_document_is_not_readable(monkeypatch):  # noqa: ANN001
    import app.api.v1.lineage as lineage_api
    import app.services.lineage_service as lineage_service

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    readable_document_id = uuid.uuid4()
    denied_document_id = uuid.uuid4()
    request_id = "req-mixed-citations"
    account_id = "acct-1"

    trace_record = {
        "tenant_id": str(tenant_id),
        "account_id": "acct-other",
        "conversation_id": str(conversation_id),
        "request_id": request_id,
        "citations": [
            {"document_id": str(readable_document_id)},
            {"document_id": str(denied_document_id)},
        ],
        "retrieval": {},
    }
    conversation = SimpleNamespace(id=conversation_id, tenant_id=tenant_id, owner_account_id=account_id, user_id=None)

    monkeypatch.setattr(lineage_api, "load_answer_lineage_trace", lambda **_kwargs: dict(trace_record), raising=True)
    monkeypatch.setattr(
        lineage_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )
    monkeypatch.setattr(
        lineage_service,
        "get_allowed_document_id_sets",
        lambda *_args, **_kwargs: ({readable_document_id}, set()),
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: _ConversationDB(conversation)
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: account_id
    app.get("/api/v1/lineage/answer/{request_id}")(lineage_api.get_answer_lineage)

    client = TestClient(app)
    response = client.get(f"/api/v1/lineage/answer/{request_id}")

    assert response.status_code == 404
