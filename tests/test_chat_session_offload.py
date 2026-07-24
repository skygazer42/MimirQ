import asyncio
import threading
import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks


@pytest.mark.asyncio
async def test_managed_retrieval_offload_owns_session_and_releases_request_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    events: list[str] = []
    loop_thread_id = threading.get_ident()
    request_db = SimpleNamespace(rollback=lambda: events.append("request_rollback"))
    worker_db = SimpleNamespace(close=lambda: events.append("worker_close"))
    monkeypatch.setattr(limiter, "SessionLocal", lambda: worker_db, raising=False)

    def work(db):  # noqa: ANN001, ANN202
        assert db is worker_db
        assert threading.get_ident() != loop_thread_id
        events.append("work")
        return "ok"

    result = await limiter.run_blocking_retrieval_call_with_managed_session(
        work,
        request_db=request_db,
    )

    assert result == "ok"
    assert events == ["request_rollback", "work", "worker_close"]


@pytest.mark.asyncio
async def test_managed_retrieval_offload_closes_worker_session_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    closed = 0

    def close() -> None:
        nonlocal closed
        closed += 1

    monkeypatch.setattr(
        limiter,
        "SessionLocal",
        lambda: SimpleNamespace(close=close),
        raising=False,
    )

    def fail(_db):  # noqa: ANN001, ANN202
        raise RuntimeError("worker failed")

    with pytest.raises(RuntimeError, match="worker failed"):
        await limiter.run_blocking_retrieval_call_with_managed_session(
            fail,
            request_db=SimpleNamespace(rollback=lambda: None),
        )

    assert closed == 1


@pytest.mark.asyncio
async def test_managed_retrieval_offload_accepts_no_request_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    worker_db = SimpleNamespace(close_calls=0)

    def close() -> None:
        worker_db.close_calls += 1

    worker_db.close = close
    monkeypatch.setattr(limiter, "SessionLocal", lambda: worker_db)

    result = await limiter.run_blocking_retrieval_call_with_managed_session(
        lambda db: db,
        request_db=None,
    )

    assert result is worker_db
    assert worker_db.close_calls == 1


@pytest.mark.asyncio
async def test_managed_retrieval_offload_tolerates_request_rollback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    worker_db = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(limiter, "SessionLocal", lambda: worker_db)

    def fail_rollback() -> None:
        raise RuntimeError("connection already invalid")

    result = await limiter.run_blocking_retrieval_call_with_managed_session(
        lambda db: db,
        request_db=SimpleNamespace(rollback=fail_rollback),
    )

    assert result is worker_db


@pytest.mark.asyncio
async def test_retrieval_explain_replaces_request_session_before_offload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.retrieval_explain as explain

    events: list[str] = []
    request_db = SimpleNamespace(rollback=lambda: events.append("request_rollback"))
    worker_db = object()
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(explain.DatasetService, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(explain.DatasetService, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(explain.DatasetService, "assert_dataset_readable", lambda *_args: None)
    monkeypatch.setattr(explain, "_enforce_non_empty_retrieval_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(explain, "build_rag_state", lambda **kwargs: dict(kwargs))

    def fake_retrieval(state):  # noqa: ANN001, ANN202
        assert state["db"] is worker_db
        return {"citations": [], "metrics": {}}

    monkeypatch.setattr(explain, "run_retrieval", fake_retrieval)

    async def managed_offload(work, *, request_db, runtime_metrics):  # noqa: ANN001, ANN202
        request_db.rollback()
        events.append("offload")
        assert runtime_metrics == {}
        return work(worker_db)

    monkeypatch.setattr(
        explain,
        "run_blocking_retrieval_call_with_managed_session",
        managed_offload,
        raising=False,
    )

    response = await explain.explain_retrieval(
        explain.RetrievalExplainRequest(query="where", dataset_id=dataset_id),
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        db=request_db,
    )

    assert response.candidate_counts == {"query_count": 0, "citations": 0}
    assert events == ["request_rollback", "offload"]


@pytest.mark.asyncio
async def test_multi_agent_retrieval_replaces_request_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.multi_agent as multi_agent

    expected_request_db = object()
    worker_db = object()

    def fake_retrieval(state):  # noqa: ANN001, ANN202
        assert state["db"] is worker_db
        return {"docs": []}

    async def managed_offload(work, *, request_db):  # noqa: ANN001, ANN202
        assert request_db is None
        return work(worker_db)

    monkeypatch.setattr(multi_agent, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(
        multi_agent,
        "run_blocking_retrieval_call_with_managed_session",
        managed_offload,
        raising=False,
    )

    runner = object.__new__(multi_agent.MultiAgentRAGRunner)
    result = await runner._run_sub_agent(
        index=0,
        query="subquery",
        base_state={"db": expected_request_db, "question": "original"},
    )

    assert result.result == {"docs": []}


@pytest.mark.asyncio
async def test_multi_agent_concurrent_retrieval_uses_distinct_closed_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.multi_agent as multi_agent
    import app.services.rag_runtime_limiter as limiter

    class WorkerSession:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    worker_sessions: list[WorkerSession] = []
    observed_sessions: list[WorkerSession] = []
    barrier = threading.Barrier(2)

    def create_worker_session() -> WorkerSession:
        worker = WorkerSession()
        worker_sessions.append(worker)
        return worker

    def fake_retrieval(state):  # noqa: ANN001, ANN202
        observed_sessions.append(state["db"])
        barrier.wait(timeout=2)
        return {"docs": []}

    monkeypatch.setattr(limiter, "SessionLocal", create_worker_session)
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 2)
    monkeypatch.setattr(multi_agent, "run_retrieval", fake_retrieval)
    runner = object.__new__(multi_agent.MultiAgentRAGRunner)
    base_state = {
        "db": object(),
        "question": "original",
    }

    await asyncio.gather(
        runner._run_sub_agent(index=0, query="one", base_state=base_state),
        runner._run_sub_agent(index=1, query="two", base_state=base_state),
    )

    assert len(worker_sessions) == 2
    assert len({id(db) for db in observed_sessions}) == 2
    assert all(db.close_calls == 1 for db in worker_sessions)


@pytest.mark.asyncio
async def test_multi_agent_fanout_rolls_back_request_session_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.multi_agent as multi_agent

    request_rollbacks = 0
    worker_sessions = [object(), object()]
    managed_request_sessions: list[object | None] = []
    engine = SimpleNamespace(
        _score_question_complexity=lambda *_args: 300.0,
        _select_llm=lambda *_args: (SimpleNamespace(model_name="fake"), "fast", "test"),
    )
    runner = multi_agent.MultiAgentRAGRunner(engine)

    def rollback() -> None:
        nonlocal request_rollbacks
        request_rollbacks += 1

    async def decompose(**_kwargs):  # noqa: ANN202
        return [
            multi_agent.MultiAgentPlanStep(query="one", rationale="test"),
            multi_agent.MultiAgentPlanStep(query="two", rationale="test"),
        ]

    async def managed_offload(work, *, request_db):  # noqa: ANN001, ANN202
        managed_request_sessions.append(request_db)
        return work(worker_sessions[len(managed_request_sessions) - 1])

    def fake_retrieval(state):  # noqa: ANN001, ANN202
        assert state["db"] in worker_sessions
        return {"docs": [], "citations": [], "metrics": {"retrieval_mode": "hybrid"}}

    monkeypatch.setattr(runner, "_decompose", decompose)
    monkeypatch.setattr(multi_agent, "build_rag_state", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(multi_agent, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(
        multi_agent,
        "run_blocking_retrieval_call_with_managed_session",
        managed_offload,
    )

    events = [
        event
        async for event in runner.stream(
            request=multi_agent.AgenticStreamRequest(
                question="question",
                db=SimpleNamespace(rollback=rollback),
            )
        )
    ]

    assert request_rollbacks == 1
    assert managed_request_sessions == [None, None]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_agentic_round_replaces_request_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    request_db = object()
    worker_db = object()
    managed_calls = 0
    engine = SimpleNamespace(
        _score_question_complexity=lambda *_args: 300.0,
        _select_llm=lambda *_args: (SimpleNamespace(model_name="fake"), "fast", "test"),
    )
    runner = rag_agent.AgenticRAGRunner(engine)

    async def plan(**_kwargs):  # noqa: ANN202
        return [rag_agent.AgenticPlanStep(query="subquery", rationale="test")]

    async def managed_offload(work, *, request_db):  # noqa: ANN001, ANN202
        nonlocal managed_calls
        assert request_db is expected_request_db
        managed_calls += 1
        return work(worker_db)

    def fake_retrieval(state):  # noqa: ANN001, ANN202
        assert state["db"] is worker_db
        return {
            "docs": [],
            "citations": [],
            "metrics": {"retrieval_mode": "hybrid"},
            "abstain_triggered": True,
            "abstain_reason": "no_evidence",
        }

    expected_request_db = request_db
    monkeypatch.setattr(runner, "_plan", plan)
    monkeypatch.setattr(rag_agent, "build_rag_state", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(rag_agent, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(
        rag_agent,
        "run_blocking_retrieval_call_with_managed_session",
        managed_offload,
    )
    monkeypatch.setattr(rag_agent.settings, "RAG_MULTI_AGENT_ENABLED", False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_TOOLS_ENABLED", False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRAG_STREAMING_ENABLED", False)

    events = [
        event
        async for event in runner.stream(
            request=rag_agent.AgenticStreamRequest(
                question="question",
                db=request_db,
            )
        )
    ]

    assert managed_calls == 1
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_chat_singleflight_follower_reacquires_after_leader_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_cache_runtime as cache_runtime
    import app.services.chat_response_cache as cache

    key = "chat-cancel-retry"
    cache.clear_inflight_chat_responses()
    monkeypatch.setattr(
        cache_runtime,
        "prepare_chat_cache_lookup",
        lambda **_kwargs: (True, key, None),
    )
    async def _get_cached(_key: str):  # noqa: ANN202
        return None

    monkeypatch.setattr(cache_runtime, "get_cached_chat_response_async", _get_cached)
    monkeypatch.setattr(cache_runtime.settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", True)
    options = SimpleNamespace()

    try:
        leader_state = await cache_runtime.prepare_non_streaming_chat_cache_state(options=options)
        assert leader_state.singleflight_leader is True

        follower = asyncio.create_task(
            cache_runtime.prepare_non_streaming_chat_cache_state(options=options)
        )
        await asyncio.sleep(0)
        cache.reject_inflight_chat_response(
            key,
            cache.InflightResponseLeaderCancelledError("leader cancelled"),
        )

        follower_state = await asyncio.wait_for(follower, timeout=0.5)
        assert follower_state.singleflight_leader is True
        assert follower_state.singleflight_hit is False
        cache.resolve_inflight_chat_response(key, {"content": "replacement"})
    finally:
        cache.clear_inflight_chat_responses()


@pytest.mark.asyncio
async def test_chat_distributed_singleflight_waits_for_redis_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_response_cache as cache

    key = "chat-distributed"
    state = {
        "payload": None,
        "lease_owner": None,
    }

    async def _get_cached(_key: str):  # noqa: ANN202
        assert _key == key
        return state["payload"]

    async def _acquire_lease(_key: str, *, value: str, ttl_sec: int):  # noqa: ANN202
        assert _key == f"{key}:lease"
        assert ttl_sec >= 60
        if state["lease_owner"] is None:
            state["lease_owner"] = value
            return True
        return False

    async def _release_lease(_key: str, *, value: str):  # noqa: ANN202
        if _key == f"{key}:lease" and state["lease_owner"] == value:
            state["lease_owner"] = None

    cache.clear_inflight_chat_responses()
    monkeypatch.setattr(cache, "get_cached_chat_response_async", _get_cached, raising=True)
    monkeypatch.setattr(cache, "try_acquire_best_effort_redis_lease", _acquire_lease, raising=True)
    monkeypatch.setattr(cache, "release_best_effort_redis_lease", _release_lease, raising=True)

    leader, leader_payload = await cache.acquire_or_wait_for_distributed_inflight_chat_response(
        key,
        response_cache_ttl_sec=30,
    )
    assert leader is True
    assert leader_payload is None
    assert state["lease_owner"] is not None

    follower = asyncio.create_task(
        cache.acquire_or_wait_for_distributed_inflight_chat_response(
            key,
            response_cache_ttl_sec=30,
        )
    )
    await asyncio.sleep(0.05)
    state["payload"] = {"content": "cached", "citations": [], "metrics": {}}
    follower_is_leader, follower_payload = await asyncio.wait_for(follower, timeout=0.5)

    assert follower_is_leader is False
    assert follower_payload == state["payload"]

    cache.resolve_inflight_chat_response(key, state["payload"])
    for _ in range(10):
        if state["lease_owner"] is None:
            break
        await asyncio.sleep(0)
    assert state["lease_owner"] is None
    cache.clear_inflight_chat_responses()


@pytest.mark.asyncio
async def test_set_cached_chat_response_schedules_async_write_in_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_response_cache as cache

    written = asyncio.Event()

    async def _fake_set(key: str, payload: dict[str, object], *, ttl_sec: int | None = None, max_value_bytes: int | None = None):  # noqa: ANN202
        assert key == "chat-write"
        assert payload["content"] == "ok"
        assert ttl_sec == 90
        assert max_value_bytes == 1234
        written.set()
        return True

    monkeypatch.setattr(cache.settings, "CHAT_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(cache.settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 90, raising=False)
    monkeypatch.setattr(cache.settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 1234, raising=False)
    monkeypatch.setattr(cache, "set_cached_chat_response_async", _fake_set, raising=True)

    assert cache.set_cached_chat_response("chat-write", {"content": "ok"}) is True
    await asyncio.wait_for(written.wait(), timeout=0.5)


@pytest.mark.asyncio
async def test_chat_singleflight_releases_lease_after_cache_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_response_cache as cache

    key = "chat-write-before-release"
    allow_write = asyncio.Event()
    released = asyncio.Event()

    async def _get_cached(_key: str):  # noqa: ANN202
        return None

    async def _acquire(*_args, **_kwargs):  # noqa: ANN202
        return True

    async def _write(*_args, **_kwargs):  # noqa: ANN202
        await allow_write.wait()
        return True

    async def _release(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        released.set()

    cache.clear_inflight_chat_responses()
    monkeypatch.setattr(cache.settings, "CHAT_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(cache, "get_cached_chat_response_async", _get_cached, raising=True)
    monkeypatch.setattr(cache, "try_acquire_best_effort_redis_lease", _acquire, raising=True)
    monkeypatch.setattr(cache, "set_cached_chat_response_async", _write, raising=True)
    monkeypatch.setattr(cache, "release_best_effort_redis_lease", _release, raising=True)

    leader, _payload = await cache.acquire_or_wait_for_distributed_inflight_chat_response(
        key,
        response_cache_ttl_sec=30,
    )
    assert leader is True
    assert cache.set_cached_chat_response(key, {"content": "ok"}) is True
    cache.resolve_inflight_chat_response(key, {"content": "ok"})
    await asyncio.sleep(0)
    assert released.is_set() is False

    allow_write.set()
    await asyncio.wait_for(released.wait(), timeout=0.5)
    cache.clear_inflight_chat_responses()


@pytest.mark.asyncio
async def test_chat_cancelled_or_overloaded_leader_releases_singleflight_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.chat as chat_api
    import app.services.chat_response_cache as cache
    from app.api.schemas.chat import ChatRequest
    from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

    key = "chat-endpoint-cancel"
    cache.clear_inflight_chat_responses()
    conversation_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    request_db = SimpleNamespace(rollback=lambda: None)
    request = ChatRequest(
        message="where",
        dataset_id=dataset_id,
        rag_config={"answer_mode": "extractive"},
    )
    effective_rag_config = request.rag_config
    runtime = SimpleNamespace(
        effective_rag_config=effective_rag_config,
        dataset_id_used=dataset_id,
        dataset_rag_defaults_applied_fields=[],
        effective_prompt_template_id=None,
        effective_prompt_template_key=None,
        effective_prompt_ab_experiment_key=None,
        dataset_prompt_defaults_applied_fields=[],
        dataset_rag_config_template_defaults_applied_fields=[],
        rag_config_template_meta=None,
        history_for_llm=[],
    )
    async def _fake_enforce_tenant_qps_quota_async(**_kwargs):  # noqa: ANN202
        return {}

    monkeypatch.setattr(
        "app.services.tenant_quota_service.enforce_tenant_qps_quota_async",
        _fake_enforce_tenant_qps_quota_async,
    )
    monkeypatch.setattr(chat_api, "check_chat_assistant_token_quota", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        chat_api,
        "_prepare_chat_turn_session",
        lambda **_kwargs: SimpleNamespace(
            conversation_id=conversation_id,
            scope_dataset_id=dataset_id,
            allowed_doc_ids=[],
            long_term_messages=[],
        ),
    )
    monkeypatch.setattr(chat_api, "_prepare_chat_request_runtime", lambda **_kwargs: runtime)

    acquired_future: asyncio.Future[dict] | None = None

    async def prepare_cache(**_kwargs):  # noqa: ANN202
        nonlocal acquired_future
        is_leader, acquired_future = await cache.acquire_inflight_chat_response(key)
        assert is_leader
        return SimpleNamespace(
            cache_feature_enabled=True,
            cache_key=key,
            cache_skip_reason=None,
            cache_eligible=True,
            cache_hit=False,
            singleflight_hit=False,
            singleflight_leader=True,
            singleflight_key=key,
            full_response="",
            citations_data=[],
            metrics_data={},
            structured_data=None,
        )

    monkeypatch.setattr(chat_api, "_prepare_non_streaming_chat_cache_state", prepare_cache)

    async def cancelled_offload(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise asyncio.CancelledError

    monkeypatch.setattr(
        chat_api,
        "run_blocking_retrieval_call_with_managed_session",
        cancelled_offload,
        raising=False,
    )

    try:
        with pytest.raises(asyncio.CancelledError):
            await chat_api.chat(
                SimpleNamespace(
                    state=SimpleNamespace(request_id="cancel-test"),
                    client=SimpleNamespace(host="127.0.0.1"),
                    headers={},
                ),
                request,
                BackgroundTasks(),
                tenant_id=uuid.uuid4(),
                account_id="member-1",
                db=request_db,
            )

        assert acquired_future is not None
        assert acquired_future.done()
        assert isinstance(acquired_future.exception(), cache.InflightResponseLeaderCancelledError)
        replacement_leader, replacement_future = await cache.acquire_inflight_chat_response(key)
        assert replacement_leader is True
        cache.resolve_inflight_chat_response(key, {"content": "replacement"})
        await replacement_future

        async def overloaded_offload(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise RetrievalAdmissionTimeoutError(0.03)

        monkeypatch.setattr(
            chat_api,
            "run_blocking_retrieval_call_with_managed_session",
            overloaded_offload,
            raising=False,
        )
        with pytest.raises(RetrievalAdmissionTimeoutError) as exc_info:
            await chat_api.chat(
                SimpleNamespace(
                    state=SimpleNamespace(request_id="overload-test"),
                    client=SimpleNamespace(host="127.0.0.1"),
                    headers={},
                ),
                request,
                BackgroundTasks(),
                tenant_id=uuid.uuid4(),
                account_id="member-1",
                db=request_db,
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.headers == {"Retry-After": "1"}
        assert acquired_future is not None
        assert acquired_future.exception() is exc_info.value
    finally:
        cache.clear_inflight_chat_responses()


@pytest.mark.asyncio
async def test_langchain_engine_releases_session_and_propagates_admission_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    import app.rag.engine as engine_mod
    import app.rag.policy.modality_router as modality_router
    import app.services.chat_tag_service as tag_service
    from app.core.config import settings
    from app.rag.engine import RAGEngine
    from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

    for name, value in {
        "ENABLE_QUERY_REWRITE": False,
        "ENABLE_MULTI_QUERY": False,
        "ENABLE_HYDE": False,
        "ENABLE_STEP_BACK_QUERY": False,
        "ENABLE_QUERY_DECOMPOSITION": False,
        "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED": False,
        "RETRIEVAL_QUERY_PARALLELISM": 1,
        "RAG_AGENTIC_MODE_ENABLED": False,
        "RAG_CORRECTIVE_ENABLED": False,
        "RAG_ABSTAIN_ENABLED": False,
        "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED": False,
        "RAG_RETRIEVAL_RAIL_ENABLED": False,
        "RAG_CONTEXT_EVIDENCE_ENABLED": False,
        "RAG_KG_QUERY_EXPANSION_ENABLED": False,
        "RAG_KG_CHUNK_INJECTION_ENABLED": False,
        "KG_ENABLED": False,
        "KG_CHAT_ENABLED": False,
        "VISION_RAG_READER_ENABLED": False,
        "VISION_RAG_GENERATION_ENABLED": False,
        "INPUT_GUARD_ENABLED": False,
        "OUTPUT_GUARD_ENABLED": False,
        "RAG_CLAIM_CHECK_ENABLED": False,
        "PII_REDACTION_ENABLED": False,
        "LLM_MOCK_ENABLED": True,
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)

    class RequestDB:
        def __init__(self) -> None:
            self.checked_out = False
            self.rollback_calls = 0

        def query(self, *_args):  # noqa: ANN002, ANN202
            self.checked_out = True
            return self

        def filter(self, *_args):  # noqa: ANN002, ANN202
            return self

        def all(self) -> list[object]:
            return []

        def rollback(self) -> None:
            self.rollback_calls += 1
            self.checked_out = False

    class Retriever:
        _last_debug_metrics: dict[str, object] = {}

        def model_copy(self, **_kwargs):  # noqa: ANN003, ANN202
            return self

        def invoke(self, _query: str) -> list[Document]:
            return [
                Document(
                    page_content="retrieved evidence",
                    id="chunk-1",
                    metadata={
                        "document_id": "doc-1",
                        "chunk_id": "chunk-1",
                        "source": "source.txt",
                        "score": 0.9,
                        "relevance_score": 0.9,
                    },
                )
            ]

    request_db = RequestDB()
    limiter_release_states: list[bool] = []
    generation_release_states: list[bool] = []
    stream_events: list[dict] = []
    generation_started = asyncio.Event()
    finish_generation = asyncio.Event()

    async def limited_call(func, *args, **_kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        limiter_release_states.append(not request_db.checked_out)
        return func(*args)

    class BlockingChain:
        def __or__(self, _other):  # noqa: ANN001, ANN202
            return self

        async def astream(self, _inputs):  # noqa: ANN001, ANN202
            generation_release_states.append(not request_db.checked_out)
            generation_started.set()
            await finish_generation.wait()
            yield "answer"

    class FakeLLM:
        model_name = "test"

        def bind(self, **_kwargs):  # noqa: ANN003, ANN202
            return self

    def build_tag_context(db, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        assert db is request_db
        request_db.checked_out = True
        return [], {"enabled": True, "used": False, "reason": "test"}

    monkeypatch.setattr(engine_mod, "hybrid_retriever", Retriever())
    monkeypatch.setattr(engine_mod, "run_blocking_retrieval_call", limited_call, raising=False)
    monkeypatch.setattr(modality_router, "classify_query_modality", lambda _query: ("table", ["test"]))
    monkeypatch.setattr(tag_service, "build_chat_tag_context_docs", build_tag_context)

    engine = RAGEngine()
    engine.prompt_template = BlockingChain()
    monkeypatch.setattr(
        engine,
        "_select_llm",
        lambda *_args, **_kwargs: (FakeLLM(), "test", "test"),
    )
    stream = engine.stream_chat(
        question="What does the evidence say?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=request_db,
        request_id="session-boundary-test",
    )

    async def consume_to_first_token() -> None:
        async for event in stream:
            stream_events.append(event)
            if event.get("type") == "error":
                raise AssertionError(event)
            if event.get("type") == "token":
                return

    consumer = asyncio.create_task(consume_to_first_token())
    try:
        generation_waiter = asyncio.create_task(generation_started.wait())
        done, _pending = await asyncio.wait(
            {consumer, generation_waiter},
            timeout=5,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if consumer in done:
            await consumer
            raise AssertionError(f"stream ended before generation: {stream_events!r}")
        assert generation_waiter in done
        assert {
            "limiter_release_states": limiter_release_states,
            "generation_release_states": generation_release_states,
            "request_db_checked_out": request_db.checked_out,
        } == {
            "limiter_release_states": [True],
            "generation_release_states": [True],
            "request_db_checked_out": False,
        }
        assert request_db.rollback_calls >= 2
    finally:
        finish_generation.set()
        await asyncio.wait_for(consumer, timeout=5)
        await stream.aclose()

    async def overloaded_call(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RetrievalAdmissionTimeoutError(0.03)

    monkeypatch.setattr(engine_mod, "run_blocking_retrieval_call", overloaded_call)
    overloaded_stream = engine.stream_chat(
        question="What does the evidence say?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=request_db,
        request_id="overload-test",
    )
    try:
        with pytest.raises(RetrievalAdmissionTimeoutError):
            async for _event in overloaded_stream:
                pass
    finally:
        await overloaded_stream.aclose()
