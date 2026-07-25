import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response


class _NoopDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_enqueue_kg_extraction_returns_none_for_duplicate_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import queue

    class _Queue:
        async def enqueue_job(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

    async def _get_queue():  # noqa: ANN202
        return _Queue()

    monkeypatch.setattr(queue, "get_queue", _get_queue, raising=True)

    result = await queue.enqueue_kg_extraction(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        requested_by="member-1",
        job_id="kg:job",
        pipeline_hash="pipe-a",
        replace_existing=True,
        prune_orphan_entities=False,
        extract_relations=None,
        extract_skills=True,
    )

    assert result is None


@pytest.mark.asyncio
async def test_enqueue_kg_extraction_forwards_frozen_effective_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.kg.extraction_job_options import build_kg_extraction_job_options
    from app.tasks import queue

    captured: dict[str, object] = {}

    class _Queue:
        async def enqueue_job(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            captured["args"] = args
            captured["kwargs"] = kwargs
            return SimpleNamespace(job_id="kg:queued")

    async def _get_queue():  # noqa: ANN202
        return _Queue()

    options = build_kg_extraction_job_options(
        pipeline_hash="pipe-a",
        prompt_template_id=uuid.uuid4(),
        prompt_template_key="prompt-a",
        prompt_ab_experiment_key="experiment-a",
        extraction_backend="hybrid",
        kg_python_plugin="plugin:queued",
        kg_python_params={"threshold": 0.75},
        replace_existing=True,
        prune_orphan_entities=False,
        extract_relations=True,
        extract_skills=False,
    )
    monkeypatch.setattr(queue, "get_queue", _get_queue, raising=True)

    result = await queue.enqueue_kg_extraction(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        requested_by="member-1",
        job_id="kg:job",
        pipeline_hash="pipe-a",
        effective_options=options,
    )

    assert result == "kg:queued"
    assert captured["args"][-1] == options


@pytest.mark.asyncio
async def test_enqueue_rebuild_indexes_returns_none_for_duplicate_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import queue

    class _Queue:
        async def enqueue_job(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

    async def _get_queue():  # noqa: ANN202
        return _Queue()

    monkeypatch.setattr(queue, "get_queue", _get_queue, raising=True)

    result = await queue.enqueue_rebuild_indexes(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        requested_by="member-1",
        job_id="rebuild:job",
    )

    assert result is None


def test_kg_pipeline_scope_rejects_missing_selected_version() -> None:
    from app.rag.kg.api import routes

    document_id = uuid.uuid4()
    chunks = [SimpleNamespace(doc_metadata={"pipeline_hash": "old-pipeline"})]

    with pytest.raises(HTTPException) as exc_info:
        routes._scope_chunks_to_pipeline(
            chunks,
            document_id=document_id,
            pipeline_hash="selected-pipeline",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == routes.KG_PIPELINE_CHUNKS_NOT_FOUND_DETAIL


@pytest.mark.asyncio
async def test_kg_enqueue_response_scopes_job_id_by_extraction_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.kg.api import routes
    from app.rag.kg.extraction_job_options import kg_extraction_job_options_fingerprint

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document = SimpleNamespace(doc_metadata={"pipeline_hash": "pipe-a"})
    db = _NoopDB()
    response = Response()
    captured: dict[str, object] = {}

    async def _enqueue(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return "kg-task-1"

    monkeypatch.setattr(routes.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(routes.settings, "KG_RELATION_ENABLED", True, raising=False)
    monkeypatch.setattr("app.tasks.queue.enqueue_kg_extraction", _enqueue, raising=True)

    prompt_template_id = uuid.uuid4()
    effective = routes.KGExtractionEffectiveOptions(
        pipeline_hash="pipe-a",
        prompt_template_id=prompt_template_id,
        prompt_template_key="prompt-a",
        prompt_ab_experiment_key="experiment-a",
        kg_python_plugin="plugin:queued",
        kg_python_params={"threshold": 0.75},
        replace_existing=True,
        prune_orphan_entities=False,
        extract_relations=None,
        extract_skills=True,
        extraction_backend="hybrid",
    )

    result = await routes._enqueue_kg_extraction_response(
        db=db,
        document=document,
        document_id=document_id,
        tenant_id=tenant_id,
        account_id="member-1",
        chunks=[SimpleNamespace(id=uuid.uuid4())],
        response=response,
        effective=effective,
    )

    assert result.chunk_count == 1
    assert response.status_code == 202
    assert response.headers["X-Task-Id"] == "kg-task-1"
    expected_options = {
        "schema": "mimirq.kg_extraction_job_options.v1",
        "pipeline_hash": "pipe-a",
        "prompt_template_id": str(prompt_template_id),
        "prompt_template_key": "prompt-a",
        "prompt_ab_experiment_key": "experiment-a",
        "extraction_backend": "hybrid",
        "kg_python_plugin": "plugin:queued",
        "kg_python_params": {"threshold": 0.75},
        "replace_existing": True,
        "prune_orphan_entities": False,
        "extract_relations": True,
        "extract_skills": True,
    }
    assert captured["effective_options"] == expected_options
    fingerprint = kg_extraction_job_options_fingerprint(expected_options)
    assert captured["job_id"] == f"kg:{tenant_id}:{document_id}:pipe-a:{fingerprint}"
    assert document.doc_metadata["kg_task_id"] == "kg-task-1"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_kg_enqueue_response_rejects_duplicate_job_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.kg.api import routes

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document = SimpleNamespace(doc_metadata={"pipeline_hash": "pipe-a", "kg_task_id": "old-task"})
    db = _NoopDB()

    async def _enqueue(**_kwargs):  # noqa: ANN202
        return None

    monkeypatch.setattr(routes.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.tasks.queue.enqueue_kg_extraction", _enqueue, raising=True)

    effective = routes.KGExtractionEffectiveOptions(
        pipeline_hash="pipe-a",
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        kg_python_plugin=None,
        kg_python_params={},
        replace_existing=True,
        prune_orphan_entities=False,
        extract_relations=False,
        extract_skills=False,
        extraction_backend=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes._enqueue_kg_extraction_response(
            db=db,
            document=document,
            document_id=document_id,
            tenant_id=tenant_id,
            account_id="member-1",
            chunks=[SimpleNamespace(id=uuid.uuid4())],
            response=Response(),
            effective=effective,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == routes.KG_EXTRACTION_ALREADY_QUEUED_DETAIL
    assert document.doc_metadata["kg_task_id"] == "old-task"
    assert db.commits == 0


@pytest.mark.asyncio
async def test_kg_enqueue_response_preserves_unversioned_chunk_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.kg.api import routes

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document = SimpleNamespace(doc_metadata={})
    captured: dict[str, object] = {}

    async def _enqueue(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return "kg-task-unversioned"

    monkeypatch.setattr(routes.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.tasks.queue.enqueue_kg_extraction", _enqueue, raising=True)

    effective = routes.KGExtractionEffectiveOptions(
        pipeline_hash=None,
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        kg_python_plugin=None,
        kg_python_params={},
        replace_existing=True,
        prune_orphan_entities=True,
        extract_relations=False,
        extract_skills=False,
        extraction_backend="llm",
    )

    await routes._enqueue_kg_extraction_response(
        db=_NoopDB(),
        document=document,
        document_id=document_id,
        tenant_id=tenant_id,
        account_id="member-1",
        chunks=[SimpleNamespace(id=uuid.uuid4(), doc_metadata={})],
        response=Response(),
        effective=effective,
    )

    assert captured["pipeline_hash"] is None
    assert captured["effective_options"]["pipeline_hash"] is None
    assert str(captured["job_id"]).startswith(f"kg:{tenant_id}:{document_id}:unversioned:")


@pytest.mark.asyncio
async def test_record_chunk_index_drift_only_enqueues_document_scoped_bm25_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import documents

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    document = SimpleNamespace(id=document_id, dataset_id=dataset_id, doc_metadata={})
    chunk = SimpleNamespace(id=chunk_id, doc_metadata={})
    db = _NoopDB()
    recorded: list[tuple[str, str | None]] = []
    enqueue_calls: list[dict[str, object]] = []

    async def _enqueue(**kwargs):  # noqa: ANN003, ANN202
        enqueue_calls.append(kwargs)
        return "reconcile-task-1"

    def _record_index_drift_item(*, marker, reconcile_task_id=None, **_kwargs):  # noqa: ANN003, ANN202
        recorded.append((str(marker.get("channel") or ""), reconcile_task_id))

    monkeypatch.setattr(documents, "_enqueue_index_drift_reconcile", _enqueue, raising=True)
    monkeypatch.setattr(
        "app.services.index_audit_service.record_index_drift_item",
        _record_index_drift_item,
        raising=True,
    )

    operation_result, _markers, reconcile_task_id = await documents._record_chunk_index_drift(
        db=db,
        document=document,
        chunk=chunk,
        tenant_id=tenant_id,
        account_id="member-1",
        operation="chunk.patch",
        strictness="warn",
        vector_error="vector write failed",
        bm25_error="bm25 update failed",
    )

    assert reconcile_task_id is None
    assert enqueue_calls == []
    assert operation_result["reconcile"] == {
        "status": "unsupported",
        "reason": "document_scoped_auto_reconcile_only_supports_bm25",
    }
    assert recorded == [("vector", None), ("bm25", None)]

    recorded.clear()
    operation_result, _markers, reconcile_task_id = await documents._record_chunk_index_drift(
        db=db,
        document=document,
        chunk=chunk,
        tenant_id=tenant_id,
        account_id="member-1",
        operation="chunk.patch",
        strictness="warn",
        vector_error=None,
        bm25_error="bm25 update failed",
    )

    assert reconcile_task_id == "reconcile-task-1"
    assert enqueue_calls == [{"tenant_id": tenant_id, "document_id": document_id, "requested_by": "member-1"}]
    assert operation_result["reconcile"] == {
        "status": "enqueued",
        "scope": "document",
        "channels": ["bm25"],
        "task_id": "reconcile-task-1",
    }
    assert recorded == [("bm25", "reconcile-task-1")]

    async def _not_enqueued(**kwargs):  # noqa: ANN003, ANN202
        enqueue_calls.append(kwargs)
        return None

    recorded.clear()
    enqueue_calls.clear()
    monkeypatch.setattr(documents, "_enqueue_index_drift_reconcile", _not_enqueued, raising=True)

    operation_result, _markers, reconcile_task_id = await documents._record_chunk_index_drift(
        db=db,
        document=document,
        chunk=chunk,
        tenant_id=tenant_id,
        account_id="member-1",
        operation="chunk.patch",
        strictness="warn",
        vector_error=None,
        bm25_error="bm25 update failed",
    )

    assert reconcile_task_id is None
    assert operation_result["reconcile"] == {
        "status": "not_enqueued",
        "scope": "document",
        "channels": ["bm25"],
        "reason": "queue_disabled_duplicate_or_unavailable",
    }
    assert recorded == [("bm25", None)]
