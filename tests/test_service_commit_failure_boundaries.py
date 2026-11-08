import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


def test_confluence_metadata_commit_failure_propagates(monkeypatch):
    from app.services.connector_execution import confluence

    db = MagicMock()
    failure = RuntimeError("connector metadata commit failed")
    db.commit.side_effect = failure
    monkeypatch.setattr(confluence, "_apply_connector_identity_metadata", lambda **k: None)
    with pytest.raises(RuntimeError) as raised:
        confluence._patch_confluence_page_document_metadata(
            db,
            doc=SimpleNamespace(doc_metadata={}),
            run=SimpleNamespace(id=uuid4()),
            page_id="page",
            title="title",
            page_url="https://example.invalid/page",
            last_modified=None,
            acl_provenance=None,
            settings_map={},
        )
    assert raised.value is failure
    db.rollback.assert_called_once()


def test_regression_progress_commit_failure_is_observable(caplog):
    from app.rag.evaluation.ragas import _commit_regression_progress

    db = MagicMock()
    failure = RuntimeError("progress commit failed")
    db.commit.side_effect = failure
    with caplog.at_level(logging.WARNING):
        _commit_regression_progress(
            db, SimpleNamespace(summary={}), mode="test", processed_cases=1, total_cases=2, evaluable_items=1
        )
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


@pytest.mark.parametrize("operation", ["prompt_usage", "metrics"])
def test_extraction_sidecar_commit_failure_is_observable(operation, monkeypatch, caplog):
    from app.rag.kg.extraction import extractor

    db = MagicMock()
    failure = RuntimeError("extraction sidecar commit failed")
    db.commit.side_effect = failure
    with caplog.at_level(logging.WARNING):
        if operation == "prompt_usage":
            chosen = SimpleNamespace(id=uuid4(), content="prompt", usage_count=0)
            monkeypatch.setattr(extractor, "resolve_prompt_template", lambda **k: chosen)
            config = SimpleNamespace(
                prompt_template_id=chosen.id, prompt_template_key=None, prompt_ab_experiment_key=None, ab_user_key=None
            )
            assert extractor._resolve_prompt_template_content(db, uuid4(), config) == ("prompt", str(chosen.id))
        else:
            document_id = uuid4()
            doc = SimpleNamespace(id=document_id, doc_metadata={})
            db.query.return_value.filter.return_value.all.return_value = [doc]
            chunk = SimpleNamespace(id=uuid4(), document_id=document_id)
            extractor._writeback_document_metadata(
                session=db,
                tenant_id=uuid4(),
                chunks=[chunk],
                kept_events=[],
                skipped_chunk_ids=set(),
                budget_skipped_chunk_ids=set(),
                skipped_short_chunk_ids=set(),
                failed_chunk_ids=set(),
                retry_chunk_ids=set(),
            )
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


def test_retry_cleanup_commit_failure_is_deferred_with_traceback(caplog):
    from app.parsing.processors.support.recovery import apply_pending_retry_cleanup

    db = MagicMock()
    failure = RuntimeError("retry cleanup commit failed")
    db.commit.side_effect = failure
    metadata = {"pipeline_hash": "p", "retry_cleanup": {"version": "1", "pipeline_hash": "p", "scope": "document"}}
    doc = SimpleNamespace(doc_metadata=metadata, chunk_count=2, total_characters=20)
    with caplog.at_level(logging.WARNING):
        result = apply_pending_retry_cleanup(
            db, db_document=doc, tenant_id=uuid4(), document_id=uuid4(), indexer_factory=MagicMock()
        )
    assert result == "deferred"
    assert doc.doc_metadata == metadata
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)


@pytest.mark.parametrize("precheck_only", [False, True])
@pytest.mark.parametrize("failure_stage", ["commit", "worker"])
def test_batch_precheck_failure_never_returns_success(failure_stage, precheck_only, tmp_path, monkeypatch, caplog):
    from app.services import document_batch_ingestion as module

    db = MagicMock()
    failure = RuntimeError("precheck run commit failed")
    if failure_stage == "commit":
        db.commit.side_effect = failure
    else:
        monkeypatch.setattr(module, "_run_precheck_scan_job", MagicMock(side_effect=failure))
    monkeypatch.setattr(module.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(module, "_link_precheck_staging_tree", lambda *a, **k: True)
    request = module._run_precheck_scan(
        db=db,
        tenant_id=uuid4(),
        account_id="owner",
        dataset=SimpleNamespace(id=uuid4()),
        staged_successful=[{}],
        precheck_only=precheck_only,
    )
    with caplog.at_level(logging.WARNING):
        if precheck_only:
            with pytest.raises(RuntimeError) as raised:
                asyncio.run(request)
            assert raised.value is failure
        else:
            assert asyncio.run(request) is None
            assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)
    db.rollback.assert_called_once()


def test_batch_precheck_compensation_preserves_original_failure(monkeypatch, caplog):
    from app.services import document_batch_ingestion as module

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=uuid4())
    failure = RuntimeError("scan failed")
    compensation = RuntimeError("failed-state commit failed")
    db.commit.side_effect = compensation
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(module, "run_dataset_precheck_scan", MagicMock(side_effect=failure))
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as raised:
        module._run_precheck_scan_job(tenant_id=uuid4(), dataset_id=uuid4(), scan_run_id=uuid4())
    assert raised.value is failure
    assert db.rollback.call_count == 2
    assert any(r.exc_info and r.exc_info[1] is compensation for r in caplog.records)
    db.close.assert_called_once()
