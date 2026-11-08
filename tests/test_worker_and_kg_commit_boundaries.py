import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.parametrize(
    "operation", ["alias_create", "alias_delete", "predicate_create", "predicate_update", "predicate_delete"]
)
@pytest.mark.parametrize("rollback_fails", [False, True])
def test_kg_authoritative_commit_and_rollback_failures_propagate(operation, rollback_fails, monkeypatch):
    from app.rag.kg.api import routes

    db = MagicMock()
    original = RuntimeError("KG primary commit failed")
    cleanup = RuntimeError("KG rollback failed")
    db.commit.side_effect = original
    if rollback_fails:
        db.rollback.side_effect = cleanup
    monkeypatch.setattr(routes, "_ensure_enabled", lambda: None)
    monkeypatch.setattr(routes, "_resolve_entity_id_via_redirects", lambda **k: k["entity_id"])
    if operation == "alias_create":
        db.query.return_value.filter_by.return_value.first.side_effect = [SimpleNamespace(id=uuid4()), None]
    args = dict(tenant_id=uuid4(), account_id="owner", db=db)
    with pytest.raises(RuntimeError) as raised:
        if operation == "alias_create":
            routes.create_kg_entity_alias(uuid4(), routes.KGEntityAliasCreateRequest(alias="Alias"), **args)
        elif operation == "alias_delete":
            routes.delete_kg_entity_alias(uuid4(), uuid4(), **args)
        elif operation == "predicate_create":
            routes.create_kg_predicate_ontology(routes.KGPredicateOntologyCreateRequest(predicate="uses"), **args)
        elif operation == "predicate_update":
            routes.update_kg_predicate_ontology(uuid4(), routes.KGPredicateOntologyUpdateRequest(), **args)
        else:
            routes.delete_kg_predicate_ontology(uuid4(), **args)
    assert raised.value is (cleanup if rollback_fails else original)
    if rollback_fails:
        assert raised.value.__context__ is original


def test_kg_cache_token_commit_failure_cannot_return_success(monkeypatch):
    from app.services import corpus_cache_tokens
    from app.tasks import jobs

    db = MagicMock()
    failure = RuntimeError("cache token commit failed")
    db.commit.side_effect = failure
    monkeypatch.setattr(jobs, "_transition_document_index_channel_best_effort", lambda *a, **k: None)
    monkeypatch.setattr(corpus_cache_tokens, "invalidate_dataset_cache_namespace", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "_extract_kg_job_result", AsyncMock(return_value={"ok": True}))
    with pytest.raises(RuntimeError) as raised:
        asyncio.run(
            jobs._finalize_kg_job_success(
                {},
                db=db,
                doc=SimpleNamespace(dataset_id=uuid4()),
                tid=uuid4(),
                started_at=time.perf_counter(),
                tenant_id=str(uuid4()),
                document_id=str(uuid4()),
                selected_pipeline_hash="p",
                events=[object()],
            )
        )
    assert raised.value is failure
    db.rollback.assert_called_once()


def test_evidence_job_audit_commit_failure_is_observable(monkeypatch, caplog):
    from app.tasks import jobs

    db = MagicMock()
    failure = RuntimeError("job audit commit failed")
    db.commit.side_effect = failure
    monkeypatch.setattr(jobs, "SessionLocal", lambda: db)
    monkeypatch.setattr(jobs, "_task_queue_redis_or_retry", lambda *a, **k: MagicMock())
    monkeypatch.setattr(jobs, "tenant_acquire", AsyncMock(return_value="semaphore"))
    monkeypatch.setattr(jobs, "tenant_release", AsyncMock())
    monkeypatch.setattr(jobs, "release_lock", AsyncMock())
    monkeypatch.setattr(jobs, "_acquire_task_lock_or_retry", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "repair_evidence_suite_reference_sources", lambda *a, **k: {})
    monkeypatch.setattr(jobs, "_job_result", AsyncMock(side_effect=lambda *a, **k: k))
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(
            jobs.evidence_reference_sources_repair_job(
                {},
                tenant_id=str(uuid4()),
                suite_id=str(uuid4()),
                requested_by="owner",
                apply=True,
                allow_approved=False,
                include_archived_items=False,
                max_items=1,
                max_refs_per_item=1,
                max_changes=1,
            )
        )
    assert result["ok"] is True
    db.rollback.assert_called_once()
    assert any(r.exc_info and r.exc_info[1] is failure for r in caplog.records)
