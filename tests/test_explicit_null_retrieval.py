import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.parametrize("allowed", [False, True])
def test_falsy_redis_enable_callback_keeps_its_decision(monkeypatch, allowed) -> None:
    import redis

    from app.core.redis_client import LazyRedisClient

    class Gate:
        def __init__(self):
            self.calls = 0

        def __bool__(self):
            return False

        def __call__(self):
            self.calls += 1
            return allowed

    created = []
    client = object()

    def create(*args, **kwargs):
        created.append((args, kwargs))
        return client

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(create))
    gate = Gate()
    result = LazyRedisClient(url="redis://unused", enabled=gate).get()
    assert result is (client if allowed else None)
    assert gate.calls > 0
    assert len(created) == (1 if allowed else 0)


def test_falsy_redis_options_preserve_zero_and_false_values(monkeypatch) -> None:
    import redis

    from app.core.redis_client import LazyRedisClient

    class Options(dict):
        def __bool__(self):
            return False

    received = []

    def create(*args, **kwargs):
        received.append(kwargs)
        return object()

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(create))
    LazyRedisClient(url="redis://unused", kwargs=Options(socket_timeout=0, decode_responses=False)).get()
    assert received == [{"socket_timeout": 0, "decode_responses": False}]


@pytest.mark.parametrize("owner", ["scope", "enrichment"])
def test_falsy_embedding_runtime_is_used_without_a_default_lookup(monkeypatch, owner) -> None:
    from app.rag.retrieval.hybrid import runtime_scope
    from app.rag.retrieval.hybrid.post_process import PostProcessMixin
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    class Runtime(DatasetEmbeddingRuntimeConfig):
        def __bool__(self):
            return False

    runtime = Runtime(
        provider="openai_compatible",
        model="test",
        api_base="",
        api_key="",
        embedding_space_hash="explicit-space",
        collection_name="test",
        dataset_scoped=False,
    )

    def unexpected(*args, **kwargs):
        pytest.fail("an explicitly supplied runtime must not be replaced")

    if owner == "scope":
        monkeypatch.setattr(runtime_scope, "default_embedding_runtime", unexpected)
        resolved = runtime_scope.resolve_runtime_scope(
            object(),
            scope=runtime_scope.RetrievalScope(tenant_id=uuid4(), account_id="account"),
            embedding_runtime=runtime,
        )
        assert resolved.runtime is runtime
    else:
        retriever = SimpleNamespace(
            tenant_id=uuid4(),
            account_id="account",
            _explicit_dataset_scope_ids=lambda: (),
            _resolve_embedding_runtime=unexpected,
        )
        result = PostProcessMixin._enrichment_runtime_state(retriever, embedding_runtime=runtime)
        assert result[3] == "explicit-space"


def test_falsy_explicit_cancellation_event_stops_retrieval(monkeypatch) -> None:
    from app.services import rag_runtime_limiter as limiter

    class Event(threading.Event):
        def __bool__(self):
            return False

    event = Event()
    event.set()
    monkeypatch.setattr(limiter, "_admission_state", threading.local())
    monkeypatch.setattr(limiter, "_configured_limit", lambda: 1)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: threading.BoundedSemaphore(1))
    monkeypatch.setattr(limiter, "_try_acquire_distributed_admission_slot", lambda **kwargs: (None, False))
    monkeypatch.setattr(limiter, "_distributed_admission_enabled", lambda _limit: False)
    called = []
    with pytest.raises(limiter.RetrievalAdmissionCancelledError):
        limiter.run_blocking_retrieval_call_sync(lambda: called.append(True), cancel_event=event)
    assert called == []


@pytest.mark.parametrize("now,scan,expected_now,expected_scan", [(0, 0, 0, 1), (None, None, 1234, None)])
def test_retention_missing_and_zero_limits_are_distinct(monkeypatch, now, scan, expected_now, expected_scan) -> None:
    from app.services import semantic_cache

    monkeypatch.setattr(semantic_cache.time, "time", lambda: 1234)
    actual_now, deletes, actual_scan = semantic_cache._semantic_cache_retention_limits(
        max_delete=5, max_scan=scan, now_epoch=now
    )
    assert actual_now == expected_now
    assert deletes == 5
    assert actual_scan == (semantic_cache._RETENTION_MAX_SCAN_DEFAULT if expected_scan is None else expected_scan)


@pytest.mark.parametrize("fields,has_gap", [([], False), (None, True)])
def test_explicit_empty_anchor_requirements_disable_default_checks(fields, has_gap) -> None:
    from app.rag.retrieval.evidence_gap import detect_evidence_gap

    result = detect_evidence_gap(citations=[{"source": "source"}], required_anchor_fields=fields)
    assert result["has_gap"] is has_gap
    assert result["required_anchor_fields"] == ([] if fields is not None else ["chunk_id", "document_id"])


@pytest.mark.parametrize("enabled,has_gap", [(False, False), (True, True)])
def test_contextual_gap_keeps_the_mandatory_recall_anchor_policy(enabled, has_gap) -> None:
    from app.rag.retrieval.orchestrator import _contextual_evidence_gap

    context = SimpleNamespace(
        must_recall_enabled=enabled,
        must_recall_expected_source_keys=[],
        must_recall_required_anchor_fields=["chunk_id", "document_id"],
    )
    result = _contextual_evidence_gap(context, [{"source": "source"}])
    assert result["has_gap"] is has_gap
    assert result["required_anchor_fields"] == (["chunk_id", "document_id"] if enabled else [])


def test_falsy_real_retriever_is_not_replaced_by_the_empty_shim(monkeypatch) -> None:
    class Retriever:
        def __bool__(self):
            return False

    retriever = Retriever()
    module = ModuleType("app.rag.retriever")
    module.hybrid_retriever = retriever
    monkeypatch.setitem(sys.modules, "app.rag.retriever", module)
    path = Path(__file__).resolve().parents[1] / "app/rag/retrieval/orchestration/retriever_shim.py"
    spec = importlib.util.spec_from_file_location("explicit_retriever_shim_check", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    assert loaded.hybrid_retriever is retriever
