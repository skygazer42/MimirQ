import asyncio
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.schemas.evaluation import EvidenceItemImportQuery
from app.api.schemas.evaluation.diagnostics import KGSearchDiagnosticsResponse, KGSearchDiagnosticsSummary
from app.api.v1.evaluation import evidence
from app.api.v1.evaluation import routes as evaluations
from app.api.v1.system import settings
from app.infrastructure.database.connection import Base
from app.models.evaluation.evidence import EvidenceItem, EvidenceSuite
from app.models.evaluation.results import RagasRegressionCase
from app.services.evaluation import case_import as evaluation_case_import


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def evidence_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[EvidenceSuite.__table__, EvidenceItem.__table__, RagasRegressionCase.__table__],
    )
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def test_evidence_sync_rolls_back_failed_link_and_continues_next_item(evidence_db, monkeypatch):
    db = evidence_db
    tenant_id, dataset_id, suite_id = uuid4(), uuid4(), uuid4()
    item_ids = [uuid4(), uuid4(), uuid4()]
    now = datetime.now(UTC)
    db.add(EvidenceSuite(id=suite_id, tenant_id=tenant_id, dataset_id=dataset_id, name="atomic sync"))
    for index, item_id in enumerate(item_ids):
        db.add(
            EvidenceItem(
                id=item_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                suite_id=suite_id,
                status="approved",
                query=f"question {index}",
                reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
                updated_at=now - timedelta(seconds=index),
            )
        )
    db.commit()
    db.execute(
        text(
            "CREATE TRIGGER reject_second_link BEFORE UPDATE OF regression_case_id ON evidence_items "
            f"WHEN NEW.id = '{item_ids[1].hex}' "
            "BEGIN SELECT RAISE(ABORT, 'link rejected'); END"
        )
    )
    db.commit()
    monkeypatch.setattr(evidence.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evidence.dataset_service, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evidence.dataset_service, "assert_dataset_writable", lambda *_args: None)
    monkeypatch.setattr(evidence, "finalize_reference_sources", lambda _db, **kwargs: kwargs["reference_sources"])

    result = evidence.sync_suite_to_regression_cases(suite_id, tenant_id=tenant_id, account_id="owner", db=db)

    assert result.created == 2
    assert result.updated == 0
    assert [error["item_id"] for error in result.errors] == [str(item_ids[1])]
    assert db.query(RagasRegressionCase).count() == 2
    assert [db.get(EvidenceItem, item_id).regression_case_id is not None for item_id in item_ids] == [
        True,
        False,
        True,
    ]
    assert db.is_active

    db.execute(text("DROP TRIGGER reject_second_link"))
    db.commit()
    retried = evidence.sync_suite_to_regression_cases(suite_id, tenant_id=tenant_id, account_id="owner", db=db)
    assert retried.created == 1
    assert retried.updated == 2
    assert retried.errors == []
    assert db.query(RagasRegressionCase).count() == 3


class BrokenNumber:
    def __int__(self):
        raise RuntimeError("numeric implementation failed")


def test_evaluation_optional_chunk_index_rejects_an_invalid_value():
    with pytest.raises(HTTPException, match="Invalid evidence_chain reference") as caught:
        evaluation_case_import._normalize_evidence_item(
            {"document_id": str(uuid4()), "chunk_id": str(uuid4()), "chunk_index": BrokenNumber()}
        )
    assert caught.value.status_code == 400
    assert isinstance(caught.value.__cause__, ValidationError)


def test_health_json_probe_does_not_hide_response_implementation_failure(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            raise RuntimeError("response implementation failed")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(settings.httpx, "AsyncClient", lambda **_kwargs: Client())
    with pytest.raises(RuntimeError, match="response implementation failed"):
        asyncio.run(settings._probe_http_json("https://example.test/health"))


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_kg_snapshot_failure_only_degrades_when_rollback_succeeds(monkeypatch, rollback_fails):
    from app.rag.evaluation.benchmarks import kg_search_diagnostics
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    tenant_id, dataset_id = uuid4(), uuid4()
    response = KGSearchDiagnosticsResponse(summary=KGSearchDiagnosticsSummary(dataset_id=dataset_id))

    async def diagnose(**_kwargs):
        return response

    class Database:
        executed_on_event_loop = False

        def add(self, _row):
            return None

        def flush(self):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                self.executed_on_event_loop = True
            raise RuntimeError("snapshot write failed")

        def rollback(self):
            if rollback_fails:
                raise RuntimeError("snapshot rollback failed")

        def close(self):
            pass

    monkeypatch.setattr(evaluations.settings, "KG_ENABLED", True)
    monkeypatch.setattr(evaluations.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evaluations.dataset_service, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evaluations.dataset_service, "assert_dataset_readable", lambda *_args: None)
    monkeypatch.setattr(kg_search_diagnostics, "run_kg_search_diagnostics", diagnose)
    payload = evaluations.KGSearchDiagnosticsRequest(dataset_id=dataset_id, persist_run=True)
    db = Database()
    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", lambda: db)
    if rollback_fails:
        with pytest.raises(RuntimeError, match="snapshot rollback failed"):
            asyncio.run(evaluations.run_kg_search_diagnostics(payload, tenant_id=tenant_id, account_id="owner", db=db))
    else:
        result = asyncio.run(
            evaluations.run_kg_search_diagnostics(payload, tenant_id=tenant_id, account_id="owner", db=db)
        )
        assert result is response
        assert result.run_id is None
    assert db.executed_on_event_loop is False


def test_evidence_import_runs_blocking_database_work_off_event_loop(monkeypatch):
    tenant_id, dataset_id, suite_id = uuid4(), uuid4(), uuid4()

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return SimpleNamespace(id=suite_id, dataset_id=dataset_id, archived_at=None)

        def all(self):
            return []

    class Database:
        def __init__(self):
            self.items = []

        def query(self, *_args):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return Query()
            raise AssertionError("database query executed in event loop")

        def add(self, item):
            self.items.append(item)

        def commit(self):
            return None

    monkeypatch.setattr(evidence.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evidence.dataset_service, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evidence.dataset_service, "assert_dataset_writable", lambda *_args: None)
    db = Database()
    file = UploadFile(filename="qa.csv", file=io.BytesIO(b"query,expected_answer\nQuestion,Answer\n"))

    async def request():
        from app.infrastructure.runtime.async_bridge import run_blocking_in_thread

        if asyncio.iscoroutinefunction(evidence.import_evidence_items):
            return await evidence.import_evidence_items(
                suite_id, file, tenant_id=tenant_id, account_id="owner", db=db, query=EvidenceItemImportQuery()
            )
        return await run_blocking_in_thread(
            evidence.import_evidence_items,
            suite_id,
            file,
            tenant_id=tenant_id,
            account_id="owner",
            db=db,
            query=EvidenceItemImportQuery(),
        )

    result = asyncio.run(request())
    assert result.created == 1
    assert result.errors == []
    assert [(item.query, item.expected_answer) for item in db.items] == [("Question", "Answer")]
