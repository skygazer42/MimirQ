"""Runtime acceptance for the previously untested Desktop transaction fixes."""

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("module_name", "helper", "resource_key"),
    [
        ("app.api.v1.datasets", "_commit_dataset_audit", "dataset_id"),
        ("app.api.v1.ingestion_runs", "_commit_ingestion_run_audit", "run_id"),
        ("app.api.v1.document_versions", "_commit_document_version_audit", "document_id"),
        ("app.rag.kg.api.routes_support.extraction", "_audit_kg_extraction", "document_id"),
    ],
)
def test_audit_degradation_has_rollback_and_traceback(module_name, helper, resource_key, caplog):
    module = importlib.import_module(module_name)
    db = MagicMock()
    failure = RuntimeError("audit persistence unavailable")
    db.commit.side_effect = failure
    with caplog.at_level(logging.WARNING):
        getattr(module, helper)(
            db, tenant_id=uuid4(), account_id="owner", action="test.audit", details={}, **{resource_key: uuid4()}
        )
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


def test_template_usage_failure_is_observable(caplog):
    from app.services.rag_config_template_resolver import record_rag_config_template_usage

    db = MagicMock()
    failure = RuntimeError("counter commit failed")
    db.commit.side_effect = failure
    with caplog.at_level(logging.WARNING):
        record_rag_config_template_usage(db, SimpleNamespace(id=uuid4(), usage_count=0))
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


def test_qa_statistics_failure_is_observable(caplog):
    from app.services.document_qa_service import _update_document_chunk_stats

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (2, 40)
    failure = RuntimeError("stats commit failed")
    db.commit.side_effect = failure
    with caplog.at_level(logging.WARNING):
        _update_document_chunk_stats(
            db, tenant_id=uuid4(), document_id=uuid4(), document=SimpleNamespace(), active_key=""
        )
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


def test_precheck_compensation_failure_is_observable(caplog):
    from app.api.v1.dataset_precheck import _mark_precheck_scan_run_failed

    db = MagicMock()
    failure = RuntimeError("compensation commit failed")
    db.commit.side_effect = failure
    row = SimpleNamespace(id=uuid4())
    with caplog.at_level(logging.WARNING):
        _mark_precheck_scan_run_failed(db, row=row, error_message="enqueue failed")
    assert row.status == "failed"
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


def test_document_version_database_cleanup_failure_returns_500(monkeypatch):
    from app.api.v1 import document_versions as module
    from app.rag import retriever

    db = MagicMock()
    failure = RuntimeError("KG cleanup commit failed")
    db.commit.side_effect = [None, failure, None]
    monkeypatch.setattr(module.dataset_service, "ensure_member", lambda *a: None)
    monkeypatch.setattr(module, "assert_document_writable_for_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(
        module, "_get_version_document_or_404", lambda **k: SimpleNamespace(status="completed", doc_metadata={})
    )
    monkeypatch.setattr(module, "_load_version_chunk_ids", lambda **k: [uuid4()])
    monkeypatch.setattr(module, "Indexer", MagicMock())
    monkeypatch.setattr(retriever, "hybrid_retriever", MagicMock())
    app = FastAPI()

    @app.delete("/version")
    def delete_version():
        return module.delete_document_version(uuid4(), "old-version", tenant_id=uuid4(), account_id="owner", db=db)

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.delete("/version").status_code == 500
    db.rollback.assert_called_once()


def test_kg_document_audit_failure_is_observable(monkeypatch, caplog):
    from app.rag.kg.api import routes
    from app.services import indexer

    db = MagicMock()
    failure = RuntimeError("KG audit commit failed")
    db.commit.side_effect = failure
    monkeypatch.setattr(routes, "_ensure_enabled", lambda: None)
    monkeypatch.setattr(routes, "filter_allowed_document_ids", lambda *a: None)
    factory = MagicMock()
    factory.return_value.delete_event_indexes.return_value = {"events_deleted": 2}
    monkeypatch.setattr(indexer, "Indexer", factory)
    with caplog.at_level(logging.WARNING):
        result = routes.delete_kg_for_document(uuid4(), tenant_id=uuid4(), account_id="owner", db=db)
    assert result.events_deleted == 2
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)
