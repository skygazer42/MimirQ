import asyncio
import threading
from uuid import uuid4

import pytest


def test_rerank_profile_budget_remains_owned_by_retrieval_options():
    from app.rag.retrieval.configuration.options import normalize_rerank_profile, resolve_rerank_search_k

    assert normalize_rerank_profile(" SWEET_SPOT ") == "sweet_spot"
    assert normalize_rerank_profile(None) is None
    assert resolve_rerank_search_k(requested_k=3, profile="sweet_spot") == 20
    assert resolve_rerank_search_k(requested_k=27, profile="sweet_spot") == 27
    assert resolve_rerank_search_k(requested_k=3, profile=None) == 3


def test_chat_cache_lookup_uses_a_worker_owned_session(monkeypatch):
    from app.services.chat import cache_flow as chat_cache_runtime
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    loop_thread = threading.get_ident()
    events = []

    class WorkerSession:
        def __init__(self):
            self.owner = threading.get_ident()
            events.append(("open", self.owner))

        def close(self):
            events.append(("close", threading.get_ident()))
            assert threading.get_ident() == self.owner

    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", WorkerSession)

    def lookup(*, options):
        assert options.db.owner == threading.get_ident() != loop_thread
        events.append(("lookup", threading.get_ident()))
        return False, None, "test"

    monkeypatch.setattr(chat_cache_runtime, "prepare_chat_cache_lookup", lookup)
    options = chat_cache_runtime.ChatCacheLookupInput(
        db=None,
        tenant_id=uuid4(),
        account_id="member",
        dataset_id=None,
        document_ids=[],
        history=[],
        enable_long_term_memory=False,
        long_term_messages=[],
        enable_structured_memory=False,
        question="query",
        rag_config={},
        prompt_config={},
        structured_output=False,
        structured_preset=None,
        use_graph=False,
    )
    result = asyncio.run(chat_cache_runtime.prepare_non_streaming_chat_cache_state(options=options))
    assert result.cache_skip_reason == "test"
    assert [event for event, _thread in events] == ["open", "lookup", "close"]


def test_chat_finalization_persists_in_worker_but_resolves_future_on_original_loop(monkeypatch):
    from app.services.chat import response_finalization as chat_persistence
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    loop_thread = threading.get_ident()
    calls = []

    class WorkerSession:
        def close(self):
            calls.append(("close", threading.get_ident()))

    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", WorkerSession)

    def persist(*, options):
        assert isinstance(options.db, WorkerSession)
        assert not options.singleflight_leader
        assert threading.get_ident() != loop_thread
        calls.append(("persist", threading.get_ident()))
        return {"persisted": True}

    monkeypatch.setattr(chat_persistence, "finalize_chat_response_sync", persist)
    monkeypatch.setattr(chat_persistence, "_resolve_singleflight_payload", lambda *_args: {"content": "answer"})
    monkeypatch.setattr(
        chat_persistence,
        "resolve_inflight_chat_response",
        lambda *_args: calls.append(("resolve", threading.get_ident())),
    )
    options = chat_persistence.ChatResponseFinalizationInput(
        db=None,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        account_id="member",
        assistant_message_id=uuid4(),
        request_id="request",
        question="query",
        document_count=0,
        full_response="answer",
        citations=[],
        metrics={},
        structured_data=None,
        dataset_id_used=None,
        cache_eligible=False,
        cache_hit=False,
        cache_key=None,
        singleflight_key="key",
        singleflight_leader=True,
        request_enable_structured_memory=False,
        ip=None,
        user_agent=None,
        enable_online_eval=False,
        retrieval_mode_default="hybrid",
    )
    assert asyncio.run(chat_persistence.finalize_chat_response(options=options)) == {"persisted": True}
    assert [name for name, _thread in calls] == ["persist", "close", "resolve"]
    assert calls[-1][1] == loop_thread


def test_connector_handoff_keeps_database_in_workers_and_queue_on_original_loop(monkeypatch):
    from datetime import UTC, datetime

    from fastapi import BackgroundTasks

    from app.api.schemas.sources.connectors import ConnectorRunCreateRequest, ConnectorRunOut
    from app.services.connectors import runs
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    loop_thread = threading.get_ident()
    events = []
    tenant_id, dataset_id, run_id = uuid4(), uuid4(), uuid4()
    run = ConnectorRunOut(
        id=run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="web",
        status="pending",
        created_at=datetime.now(UTC),
    )

    class WorkerSession:
        def __init__(self):
            self.owner = threading.get_ident()
            assert self.owner != loop_thread

        def close(self):
            assert threading.get_ident() == self.owner
            events.append("close")

    def create_pending(db, **_kwargs):
        assert db.owner == threading.get_ident() != loop_thread
        events.append("persist_pending")
        return run

    def persist_handoff(db, **kwargs):
        assert db.owner == threading.get_ident() != loop_thread
        events.append("persist_task")
        return run.model_copy(update={"task_id": kwargs["task_id"]})

    async def enqueue(**_kwargs):
        assert threading.get_ident() == loop_thread
        events.append("enqueue")
        return "task-37"

    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", WorkerSession)
    monkeypatch.setattr(runs.settings, "TASK_QUEUE_ENABLED", True)
    monkeypatch.setattr(runs, "_validate_connector_run_enabled", lambda *_args: None)
    monkeypatch.setattr(runs.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(
        runs.dataset_service, "resolve_writable_dataset", lambda *_args: type("Dataset", (), {"id": dataset_id})()
    )
    monkeypatch.setattr(runs, "_validate_and_encrypt_run_config", lambda *_args: (None, {}))
    monkeypatch.setattr(runs, "_assert_connector_run_groups_exist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runs, "_create_pending_connector_run", create_pending)
    monkeypatch.setattr(runs, "_run_out", lambda value: value)
    monkeypatch.setattr(runs, "_connector_run_dispatcher", lambda *_args: object())
    monkeypatch.setattr(runs, "_enqueue_connector_run_if_enabled", enqueue)
    monkeypatch.setattr(runs, "_persist_run_handoff", persist_handoff)
    result = asyncio.run(
        runs.create_run(
            payload=ConnectorRunCreateRequest(connector_id="web", dataset_id=dataset_id, config={}),
            background_tasks=BackgroundTasks(),
            db=None,
            tenant_id=tenant_id,
            account_id="member",
        )
    )
    assert result.task_id == "task-37"
    assert events == ["persist_pending", "close", "enqueue", "persist_task", "close"]


def test_document_cancellation_persists_in_its_worker_session(monkeypatch):
    from types import SimpleNamespace

    from app.services.documents import processing

    loop_thread = threading.get_ident()
    events = []
    document = SimpleNamespace(status="processing", doc_metadata={})

    class Session:
        def __enter__(self):
            assert threading.get_ident() != loop_thread
            events.append("open")
            return self

        def __exit__(self, *_args):
            events.append("close")

        def commit(self):
            assert threading.get_ident() != loop_thread
            events.append("commit")

        def refresh(self, _document):
            assert threading.get_ident() != loop_thread

    monkeypatch.setattr(processing, "SessionLocal", Session)
    monkeypatch.setattr(processing.settings, "TASK_QUEUE_ENABLED", False)
    monkeypatch.setattr(processing.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(processing, "_get_document", lambda **_kwargs: document)
    monkeypatch.setattr(processing, "assert_document_writable_for_lifecycle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(processing, "_document_status_payload", lambda row: {"status": row.status})
    result = asyncio.run(
        processing.cancel_document(document_id=uuid4(), tenant_id=uuid4(), account_id="member", db=None)
    )
    assert result == {"status": "cancelled"}
    assert document.doc_metadata["cancel_requested"] is True
    assert events == ["open", "commit", "close"]


@pytest.mark.parametrize("failure", [RuntimeError("distributed wait failed"), asyncio.CancelledError()])
def test_chat_cache_preparation_failure_releases_its_local_leader(monkeypatch, failure):
    from app.services.chat import cache_flow as runtime
    from app.services.chat import response_cache as cache
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    key = "preparation-failure-test"

    class Session:
        def close(self):
            pass

    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", Session)
    monkeypatch.setattr(runtime, "prepare_chat_cache_lookup", lambda **_kwargs: (True, key, None))
    monkeypatch.setattr(runtime.settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", True)

    async def cache_miss(_key):
        return None

    async def failed_distributed_wait(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(runtime, "get_cached_chat_response_async", cache_miss)
    monkeypatch.setattr(runtime, "acquire_or_wait_for_distributed_inflight_chat_response", failed_distributed_wait)
    options = runtime.ChatCacheLookupInput(
        db=None,
        tenant_id=uuid4(),
        account_id="member",
        dataset_id=uuid4(),
        document_ids=[],
        history=[],
        enable_long_term_memory=False,
        long_term_messages=[],
        enable_structured_memory=False,
        question="query",
        rag_config={},
        prompt_config={},
        structured_output=False,
        structured_preset=None,
        use_graph=False,
    )

    async def request():
        cache.clear_inflight_chat_responses()
        try:
            with pytest.raises(type(failure)):
                await runtime.prepare_non_streaming_chat_cache_state(options=options)
            leader, _future = await cache.acquire_inflight_chat_response(key)
            assert leader is True
        finally:
            cache.clear_inflight_chat_responses()

    asyncio.run(request())
