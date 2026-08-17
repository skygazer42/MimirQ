import datetime as _dt
from types import SimpleNamespace
from uuid import uuid4

import starlette.status as _status

if not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc
if not hasattr(_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _status.HTTP_413_CONTENT_TOO_LARGE = _status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
if not hasattr(_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _status.HTTP_422_UNPROCESSABLE_CONTENT = _status.HTTP_422_UNPROCESSABLE_ENTITY

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import dataset_analysis as dataset_analysis_api
from app.core.database import get_db
from app.core.exceptions import register_exception_handlers
from app.models.chat import Conversation, Message
from app.models.feedback import MessageFeedback
from app.services import dataset_analysis_service


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, *, conversations=None, messages=None, feedback_rows=None):
        self._rows = {
            Conversation: list(conversations or []),
            Message: list(messages or []),
            MessageFeedback: list(feedback_rows or []),
        }

    def query(self, model):
        return _FakeQuery(self._rows.get(model, []))


def _build_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    dataset_id = str(uuid4())
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(dataset_analysis_api.router, prefix="/api/v1/datasets")
    app.dependency_overrides[get_tenant_id] = lambda: str(uuid4())
    app.dependency_overrides[get_current_account_id] = lambda: "reader-1"
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(dataset_analysis_api.DatasetService, "ensure_member", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService,
        "get_dataset",
        lambda *_a, **_k: SimpleNamespace(id=dataset_id, name="Dataset A"),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True
    )
    monkeypatch.setattr(
        dataset_analysis_api.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True
    )
    return TestClient(app), dataset_id


def test_load_dataset_scope_rows_raises_typed_source_incomplete_on_trace_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    db = _FakeDB(
        conversations=[SimpleNamespace(id=uuid4(), tenant_id=tenant_id, dataset_id=dataset_id)],
    )

    monkeypatch.setattr(
        dataset_analysis_service,
        "list_rag_traces",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("trace backend down")),
        raising=True,
    )

    with pytest.raises(dataset_analysis_service.DatasetAnalysisSourceIncompleteError) as excinfo:
        dataset_analysis_service._load_dataset_scope_rows(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            from_ts=None,
            to_ts=None,
            feedback_polarity=None,
        )

    assert excinfo.value.error_code == "source_incomplete"


def test_load_dataset_scope_rows_allows_empty_scope_without_traces(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    db = _FakeDB()
    monkeypatch.setattr(
        dataset_analysis_service,
        "list_rag_traces",
        lambda **_k: pytest.fail("trace loader should not run when no conversations exist"),
        raising=True,
    )

    rows = dataset_analysis_service._load_dataset_scope_rows(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        from_ts=None,
        to_ts=None,
        feedback_polarity=None,
    )

    assert rows == []


def test_summary_endpoint_returns_typed_source_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    client, dataset_id = _build_client(monkeypatch)
    monkeypatch.setattr(
        dataset_analysis_api,
        "build_dataset_analysis_summary",
        lambda **_k: (_ for _ in ()).throw(
            dataset_analysis_service.DatasetAnalysisSourceIncompleteError(dataset_id=dataset_id)
        ),
        raising=True,
    )

    response = client.get(f"/api/v1/datasets/{dataset_id}/analysis/summary")

    assert response.status_code == 503
    assert response.json()["error"] == "source_incomplete"


def test_glossary_writeback_does_not_write_when_sources_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"write": False}

    monkeypatch.setattr(
        dataset_analysis_service,
        "_build_full_bundle",
        lambda **_k: (_ for _ in ()).throw(
            dataset_analysis_service.DatasetAnalysisSourceIncompleteError(dataset_id=str(uuid4()))
        ),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_analysis_service,
        "write_glossary_candidates",
        lambda *_a, **_k: called.__setitem__("write", True),
        raising=True,
    )

    with pytest.raises(dataset_analysis_service.DatasetAnalysisSourceIncompleteError):
        dataset_analysis_service.writeback_dataset_analysis_glossary_candidates(
            db=object(),
            tenant_id=uuid4(),
            dataset_id=uuid4(),
            dataset_name="Dataset A",
            ruleset_name="core",
        )

    assert called["write"] is False
