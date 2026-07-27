import concurrent.futures
import threading
import time
import uuid
from types import SimpleNamespace

import pytest


class _FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, bytes | str] = {}
        self._expires_at: dict[str, float] = {}

    def _purge_expired(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is not None and expires_at <= time.monotonic():
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    def get(self, key: str):  # noqa: ANN201
        self._purge_expired(key)
        return self._values.get(key)

    def set(self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False) -> bool:
        self._purge_expired(key)
        if nx and key in self._values:
            return False
        self._values[key] = value
        if ex is not None:
            self._expires_at[key] = time.monotonic() + max(1, int(ex))
        else:
            self._expires_at.pop(key, None)
        return True

    def eval(self, script: str, _numkeys: int, key: str, value: str, *args: str) -> int:
        self._purge_expired(key)
        current = self._values.get(key)
        if isinstance(current, bytes):
            current = current.decode("utf-8", "ignore")
        if current != value:
            return 0
        if "EXPIRE" in script:
            ttl_sec = int(args[0]) if args else 0
            if ttl_sec <= 0:
                return 0
            self._expires_at[key] = time.monotonic() + ttl_sec
            return 1
        self._values.pop(key, None)
        self._expires_at.pop(key, None)
        return 1


def _patch_fake_candidate_redis(monkeypatch: pytest.MonkeyPatch, cache_mod, redis: _FakeRedis) -> None:  # noqa: ANN001
    monkeypatch.setattr(cache_mod, "_get_redis_client", lambda: redis, raising=True)
    monkeypatch.setattr(cache_mod, "_invalidate_redis_client", lambda: None, raising=True)
    monkeypatch.setattr(cache_mod.settings, "SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes", raising=False)
    monkeypatch.setattr(cache_mod.settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(cache_mod.settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 30, raising=False)


def test_distributed_retrieval_singleflight_follower_reuses_cached_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)
    cache_mod.clear_inflight_retrieval_candidates()

    key = "retrieval-distributed"
    leader, payload, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates(key)
    assert leader is True
    assert payload is None
    assert lease is not None

    follower_result: dict[str, object] = {}

    def _follower() -> None:
        follower_result["value"] = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates(key)

    thread = threading.Thread(target=_follower)
    thread.start()
    time.sleep(0.05)
    assert cache_mod.set_cached_retrieval_candidates(key, [{"chunk_id": "chunk-1", "content": "cached"}]) is True
    thread.join(timeout=1.0)

    follower_is_leader, follower_payload, follower_lease = follower_result["value"]  # type: ignore[misc]
    assert follower_is_leader is False
    assert follower_payload == [{"chunk_id": "chunk-1", "content": "cached"}]
    assert follower_lease is None

    cache_mod.release_distributed_inflight_retrieval_candidates(lease)
    cache_mod.clear_inflight_retrieval_candidates()


def test_distributed_retrieval_singleflight_release_is_owner_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)

    leader, _payload, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("owner-safe")
    assert leader is True
    assert lease is not None
    wrong_owner_lease = type(lease)(lease_key=lease.lease_key, owner="someone-else")

    cache_mod.release_distributed_inflight_retrieval_candidates(wrong_owner_lease)
    assert redis.get(lease.lease_key) == lease.owner

    cache_mod.release_distributed_inflight_retrieval_candidates(lease)
    assert redis.get(lease.lease_key) is None


def test_distributed_retrieval_singleflight_fails_open_when_redis_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    class _BrokenRedis(_FakeRedis):
        def set(self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False) -> bool:  # noqa: ARG002
            raise RuntimeError("redis unavailable")

    _patch_fake_candidate_redis(monkeypatch, cache_mod, _BrokenRedis())

    leader, payload, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("fail-open")

    assert leader is True
    assert payload is None
    assert lease is None


def test_distributed_retrieval_singleflight_wait_timeout_does_not_fan_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)
    monkeypatch.setattr(
        cache_mod.settings,
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC",
        2.0,
        raising=False,
    )
    clock = [0.0]
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock[0], raising=True)
    monkeypatch.setattr(cache_mod.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay), raising=True)

    leader, _payload, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("bounded-wait")
    assert leader is True
    assert lease is not None

    with pytest.raises(cache_mod.RetrievalCandidateSingleflightTimeoutError):
        cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("bounded-wait")
    assert 2.0 <= clock[0] < 2.25

    cache_mod.release_distributed_inflight_retrieval_candidates(lease)


def test_distributed_retrieval_singleflight_rechecks_cache_after_acquiring_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)
    payload = [{"chunk_id": "chunk-1", "content": "cached"}]
    calls = {"count": 0}

    def _cached(key: str):  # noqa: ANN001
        calls["count"] += 1
        return None if calls["count"] == 1 else list(payload)

    monkeypatch.setattr(cache_mod, "get_cached_retrieval_candidates", _cached, raising=True)

    leader, result, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("race")

    assert leader is False
    assert result == payload
    assert lease is None
    assert redis.get("race:lease") is None


def test_distributed_retrieval_singleflight_works_when_result_cache_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)
    monkeypatch.setattr(cache_mod.settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False, raising=False)
    cache_mod.clear_inflight_retrieval_candidates()

    key = "distributed-only"
    leader, payload, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates(key)
    assert leader is True
    assert payload is None
    assert lease is not None

    follower_result: dict[str, object] = {}

    def _follower() -> None:
        follower_result["value"] = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates(key)

    thread = threading.Thread(target=_follower)
    thread.start()
    time.sleep(0.05)
    published = cache_mod.publish_distributed_inflight_retrieval_candidates(
        key,
        [{"chunk_id": "chunk-1", "content": "shared"}],
    )
    thread.join(timeout=1.0)

    assert published is True
    follower_is_leader, follower_payload, follower_lease = follower_result["value"]  # type: ignore[misc]
    assert follower_is_leader is False
    assert follower_payload == [{"chunk_id": "chunk-1", "content": "shared"}]
    assert follower_lease is None

    cache_mod.release_distributed_inflight_retrieval_candidates(lease)
    cache_mod.clear_inflight_retrieval_candidates()


def test_distributed_singleflight_payload_is_encrypted_at_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)
    monkeypatch.setattr(cache_mod.settings, "SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes", raising=False)
    key = "encrypted-singleflight"
    payload = [{"chunk_id": "chunk-1", "content": "private document text"}]

    assert cache_mod.publish_distributed_inflight_retrieval_candidates(key, payload) is True

    raw = redis.get(f"{key}:result")
    assert raw is not None
    raw_text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    assert raw_text.startswith("enc:v1:")
    assert "private document text" not in raw_text
    assert cache_mod.get_distributed_inflight_retrieval_candidates(key) == payload


def test_distributed_retrieval_singleflight_starts_and_stops_lease_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)
    monkeypatch.setattr(
        cache_mod,
        "_retrieval_candidate_singleflight_lease_renew_interval_sec",
        lambda ttl_sec: 0.01,
        raising=True,
    )
    extend_calls: list[str] = []
    extended = threading.Event()
    original_extend = cache_mod.extend_redis_lease

    def _extend(client, key: str, *, value: str, ttl_sec: int) -> bool:  # noqa: ANN001
        extend_calls.append(key)
        extended.set()
        return bool(original_extend(client, key, value=value, ttl_sec=ttl_sec))

    monkeypatch.setattr(cache_mod, "extend_redis_lease", _extend, raising=True)

    leader, payload, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("heartbeat")

    assert leader is True
    assert payload is None
    assert lease is not None
    assert extended.wait(timeout=0.5) is True

    cache_mod.release_distributed_inflight_retrieval_candidates(lease)
    count_after_release = len(extend_calls)
    time.sleep(0.05)

    assert count_after_release >= 1
    assert len(extend_calls) == count_after_release
    assert redis.get(lease.lease_key) is None


def test_wait_for_inflight_timeout_does_not_clear_shared_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    cache_mod.clear_inflight_retrieval_candidates()
    key = "local-timeout-preserves-future"

    leader, shared_future = cache_mod.acquire_inflight_retrieval_candidates(key)
    assert leader is True
    follower_is_leader, follower_future = cache_mod.acquire_inflight_retrieval_candidates(key)
    assert follower_is_leader is False
    assert follower_future is shared_future

    original_result = concurrent.futures.Future.result
    timed_out_once = {"done": False}

    def _result(self, timeout=None):  # noqa: ANN001
        if self is follower_future and not timed_out_once["done"]:
            timed_out_once["done"] = True
            raise concurrent.futures.TimeoutError()
        return original_result(self, timeout=timeout)

    monkeypatch.setattr(concurrent.futures.Future, "result", _result, raising=True)

    with pytest.raises(cache_mod.RetrievalCandidateSingleflightTimeoutError, match="singleflight timed out"):
        cache_mod.wait_for_inflight_retrieval_candidates(key, follower_future, timeout_sec=0.01)

    assert cache_mod._inflight_candidate_futures[key] is shared_future

    late_follower_is_leader, late_follower_future = cache_mod.acquire_inflight_retrieval_candidates(key)
    assert late_follower_is_leader is False
    assert late_follower_future is shared_future

    payload = [{"chunk_id": "chunk-1", "content": "resolved later"}]
    cache_mod.resolve_inflight_retrieval_candidates(key, payload)

    assert cache_mod.wait_for_inflight_retrieval_candidates(key, late_follower_future, timeout_sec=1.0) == payload
    cache_mod.clear_inflight_retrieval_candidates()


def test_hybrid_search_releases_distributed_lease_after_candidate_cache_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    order: list[str] = []

    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )

    for name, value in {
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC": 30,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(retriever_module.settings, name, value, raising=False)

    monkeypatch.setattr(HybridRetriever, "_explicit_dataset_scope_ids", lambda self: (), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_resolve_document_dataset_scope", lambda self, *, tenant_id, document_ids: ((), False), raising=True)  # noqa: ANN001,ARG005,E501
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_candidate_cache_corpus_token", lambda self, **kwargs: "corpus-token", raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_deduplicate_results", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_apply_document_diversity", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_apply_metadata_exact_anchor_post_ordering", lambda self, query, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_merge_results", lambda self, vector_results, *args, **kwargs: list(vector_results), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(retriever_module, "emit_stream_event", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        retriever_module,
        "get_vector_store",
        lambda: SimpleNamespace(
            search=lambda **kwargs: [
                {
                    "chunk_id": "chunk-1",
                    "content": "cached result",
                    "score": 0.9,
                    "metadata": {
                        "chunk_id": "chunk-1",
                        "document_id": str(document_id),
                        "dataset_id": str(dataset_id),
                        "embedding_space_hash": runtime.embedding_space_hash,
                    },
                }
            ]
        ),
        raising=True,
    )
    monkeypatch.setattr(retriever_module, "acquire_or_wait_for_distributed_inflight_retrieval_candidates", lambda key: (True, None, SimpleNamespace(lease_key=f"{key}:lease", owner="owner-1")), raising=True)  # noqa: ANN001,E501
    monkeypatch.setattr(retriever_module, "set_cached_retrieval_candidates", lambda key, payload: order.append("write") or True, raising=True)  # noqa: ANN001
    monkeypatch.setattr(retriever_module, "release_distributed_inflight_retrieval_candidates", lambda lease: order.append("release"), raising=True)  # noqa: ANN001

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=None,
        document_ids=[document_id],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    from app.rag.retrieval_candidate_cache import clear_inflight_retrieval_candidates

    clear_inflight_retrieval_candidates()
    try:
        out = retriever._hybrid_search(
            "singleflight order",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            document_ids=[document_id],
            retrieval_mode="vector",
        )
    finally:
        clear_inflight_retrieval_candidates()

    assert [item["content"] for item in out] == ["cached result"]
    assert order == ["write", "release"]


def test_hybrid_search_publishes_distributed_result_before_semantic_cache_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    import app.services.semantic_cache as semantic_cache_module
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    order: list[str] = []

    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )

    for name, value in {
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": True,
        "SEMANTIC_CACHE_ENABLED": True,
        "SEMANTIC_CACHE_TTL_SEC": 30,
    }.items():
        monkeypatch.setattr(retriever_module.settings, name, value, raising=False)

    monkeypatch.setattr(HybridRetriever, "_explicit_dataset_scope_ids", lambda self: (), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_resolve_document_dataset_scope", lambda self, *, tenant_id, document_ids: ((), False), raising=True)  # noqa: ANN001,ARG005,E501
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_candidate_cache_corpus_token", lambda self, **kwargs: "corpus-token", raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_deduplicate_results", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_apply_document_diversity", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_apply_metadata_exact_anchor_post_ordering", lambda self, query, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_merge_results", lambda self, vector_results, *args, **kwargs: list(vector_results), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(retriever_module, "emit_stream_event", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        retriever_module,
        "get_vector_store",
        lambda: SimpleNamespace(
            search=lambda **kwargs: [
                {
                    "chunk_id": "chunk-1",
                    "content": "semantic cache result",
                    "score": 0.9,
                    "metadata": {
                        "chunk_id": "chunk-1",
                        "document_id": str(document_id),
                        "dataset_id": str(dataset_id),
                        "embedding_space_hash": runtime.embedding_space_hash,
                    },
                }
            ]
        ),
        raising=True,
    )
    monkeypatch.setattr(retriever_module, "acquire_or_wait_for_distributed_inflight_retrieval_candidates", lambda key: (True, None, SimpleNamespace(lease_key=f"{key}:lease", owner="owner-1")), raising=True)  # noqa: ANN001,E501
    monkeypatch.setattr(retriever_module, "publish_distributed_inflight_retrieval_candidates", lambda key, payload: order.append("publish") or True, raising=True)  # noqa: ANN001
    monkeypatch.setattr(retriever_module, "resolve_inflight_retrieval_candidates", lambda key, payload: order.append("resolve"), raising=True)  # noqa: ANN001
    monkeypatch.setattr(retriever_module, "release_distributed_inflight_retrieval_candidates", lambda lease: order.append("release"), raising=True)  # noqa: ANN001
    monkeypatch.setattr(
        semantic_cache_module,
        "get_cached_semantic_payload",
        lambda **kwargs: (None, {"enabled": True, "hit": False}),
        raising=True,
    )
    monkeypatch.setattr(
        semantic_cache_module,
        "set_cached_semantic_payload",
        lambda **kwargs: order.append("semantic-write") or True,
        raising=True,
    )

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=None,
        document_ids=[document_id],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    from app.rag.retrieval_candidate_cache import clear_inflight_retrieval_candidates

    clear_inflight_retrieval_candidates()
    try:
        out = retriever._hybrid_search(
            "semantic singleflight",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            document_ids=[document_id],
            retrieval_mode="vector",
        )
    finally:
        clear_inflight_retrieval_candidates()

    assert [item["content"] for item in out] == ["semantic cache result"]
    assert order[:4] == ["publish", "resolve", "release", "semantic-write"]


def test_hybrid_search_singleflight_only_uses_behavior_hash_in_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )
    key_calls: list[dict[str, object]] = []

    for name, value in {
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(retriever_module.settings, name, value, raising=False)

    monkeypatch.setattr(HybridRetriever, "_explicit_dataset_scope_ids", lambda self: (), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_resolve_document_dataset_scope", lambda self, *, tenant_id, document_ids: ((), False), raising=True)  # noqa: ANN001,ARG005,E501
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_candidate_cache_corpus_token", lambda self, **kwargs: "corpus-token", raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_deduplicate_results", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_apply_document_diversity", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_apply_metadata_exact_anchor_post_ordering", lambda self, query, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_merge_results", lambda self, vector_results, *args, **kwargs: list(vector_results), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(retriever_module, "emit_stream_event", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        retriever_module,
        "get_vector_store",
        lambda: SimpleNamespace(
            search=lambda **kwargs: [
                {
                    "chunk_id": "chunk-1",
                    "content": "singleflight result",
                    "score": 0.9,
                    "metadata": {
                        "chunk_id": "chunk-1",
                        "document_id": str(document_id),
                        "dataset_id": str(dataset_id),
                        "embedding_space_hash": runtime.embedding_space_hash,
                    },
                }
            ]
        ),
        raising=True,
    )
    monkeypatch.setattr(
        retriever_module,
        "build_retrieval_candidate_cache_key",
        lambda **kwargs: key_calls.append(kwargs) or f"cache-key-{len(key_calls)}",
        raising=True,
    )
    monkeypatch.setattr(retriever_module, "acquire_or_wait_for_distributed_inflight_retrieval_candidates", lambda key: (True, None, None), raising=True)  # noqa: ANN001,E501
    monkeypatch.setattr(retriever_module, "publish_distributed_inflight_retrieval_candidates", lambda key, payload: True, raising=True)  # noqa: ANN001,E501
    monkeypatch.setattr(retriever_module, "release_distributed_inflight_retrieval_candidates", lambda lease: None, raising=True)  # noqa: ANN001

    retriever_a = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=None,
        document_ids=[document_id],
        retrieval_mode="vector",
        alpha=0.25,
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )
    retriever_b = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=None,
        document_ids=[document_id],
        retrieval_mode="vector",
        alpha=0.75,
        enable_reranker=True,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    from app.rag.retrieval_candidate_cache import clear_inflight_retrieval_candidates

    clear_inflight_retrieval_candidates()
    try:
        retriever_a._hybrid_search(
            "behavior key",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            document_ids=[document_id],
            retrieval_mode="vector",
            alpha=0.25,
        )
        retriever_b._hybrid_search(
            "behavior key",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            document_ids=[document_id],
            retrieval_mode="vector",
            alpha=0.75,
        )
    finally:
        clear_inflight_retrieval_candidates()

    assert len(key_calls) == 2
    assert isinstance(key_calls[0]["behavior_hash"], str) and key_calls[0]["behavior_hash"]
    assert isinstance(key_calls[1]["behavior_hash"], str) and key_calls[1]["behavior_hash"]
    assert key_calls[0]["behavior_hash"] != key_calls[1]["behavior_hash"]


def test_hybrid_search_uses_distributed_singleflight_when_exact_cache_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )
    leader_calls: list[str] = []

    for name, value in {
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC": 30,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(retriever_module.settings, name, value, raising=False)

    monkeypatch.setattr(HybridRetriever, "_explicit_dataset_scope_ids", lambda self: (), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_resolve_document_dataset_scope", lambda self, *, tenant_id, document_ids: ((), False), raising=True)  # noqa: ANN001,ARG005,E501
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_candidate_cache_corpus_token", lambda self, **kwargs: "corpus-token", raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_deduplicate_results", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_apply_document_diversity", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_apply_metadata_exact_anchor_post_ordering", lambda self, query, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_merge_results", lambda self, vector_results, *args, **kwargs: list(vector_results), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(retriever_module, "emit_stream_event", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        retriever_module,
        "get_vector_store",
        lambda: SimpleNamespace(
            search=lambda **kwargs: [
                {
                    "chunk_id": "chunk-1",
                    "content": "distributed result",
                    "score": 0.9,
                    "metadata": {
                        "chunk_id": "chunk-1",
                        "document_id": str(document_id),
                        "dataset_id": str(dataset_id),
                        "embedding_space_hash": runtime.embedding_space_hash,
                    },
                }
            ]
        ),
        raising=True,
    )
    monkeypatch.setattr(
        retriever_module,
        "acquire_or_wait_for_distributed_inflight_retrieval_candidates",
        lambda key: leader_calls.append(key) or (True, None, SimpleNamespace(lease_key=f"{key}:lease", owner="owner-1")),
        raising=True,
    )
    monkeypatch.setattr(retriever_module, "publish_distributed_inflight_retrieval_candidates", lambda key, payload: True, raising=True)  # noqa: ANN001,E501
    monkeypatch.setattr(retriever_module, "release_distributed_inflight_retrieval_candidates", lambda lease: None, raising=True)  # noqa: ANN001

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=None,
        document_ids=[document_id],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    from app.rag.retrieval_candidate_cache import clear_inflight_retrieval_candidates

    clear_inflight_retrieval_candidates()
    try:
        out = retriever._hybrid_search(
            "distributed only",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            document_ids=[document_id],
            retrieval_mode="vector",
        )
    finally:
        clear_inflight_retrieval_candidates()

    assert [item["content"] for item in out] == ["distributed result"]
    assert len(leader_calls) == 1
    assert float(retriever._last_channel_metrics["cache"]["distributed_singleflight_wait_ms"]) >= 0.0


def test_hybrid_search_keeps_local_followers_when_distributed_singleflight_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )
    search_started = threading.Event()
    outputs: list[list[dict[str, object]]] = []
    failures: list[BaseException] = []

    for name, value in {
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(retriever_module.settings, name, value, raising=False)

    monkeypatch.setattr(HybridRetriever, "_explicit_dataset_scope_ids", lambda self: (), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_resolve_document_dataset_scope", lambda self, *, tenant_id, document_ids: ((), False), raising=True)  # noqa: ANN001,ARG005,E501
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_resolve_candidate_cache_corpus_token", lambda self, **kwargs: "corpus-token", raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_deduplicate_results", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_apply_document_diversity", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_apply_metadata_exact_anchor_post_ordering", lambda self, query, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_merge_results", lambda self, vector_results, *args, **kwargs: list(vector_results), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(retriever_module, "emit_stream_event", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(
        retriever_module,
        "get_vector_store",
        lambda: SimpleNamespace(
            search=lambda **kwargs: (
                search_started.set()
                or time.sleep(0.05)
                or [
                    {
                        "chunk_id": "chunk-1",
                        "content": "local future survives",
                        "score": 0.9,
                        "metadata": {
                            "chunk_id": "chunk-1",
                            "document_id": str(document_id),
                            "dataset_id": str(dataset_id),
                            "embedding_space_hash": runtime.embedding_space_hash,
                        },
                    }
                ]
            )
        ),
        raising=True,
    )
    monkeypatch.setattr(
        retriever_module,
        "acquire_or_wait_for_distributed_inflight_retrieval_candidates",
        lambda key: (_ for _ in ()).throw(RuntimeError("distributed helper failed")),
        raising=True,
    )
    monkeypatch.setattr(retriever_module, "publish_distributed_inflight_retrieval_candidates", lambda key, payload: True, raising=True)  # noqa: ANN001,E501
    monkeypatch.setattr(retriever_module, "release_distributed_inflight_retrieval_candidates", lambda lease: None, raising=True)  # noqa: ANN001

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=None,
        document_ids=[document_id],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    def _run() -> None:
        try:
            outputs.append(
                retriever._hybrid_search(
                    "distributed failure fallback",
                    top_k=1,
                    score_threshold=0.0,
                    tenant_id=tenant_id,
                    document_ids=[document_id],
                    retrieval_mode="vector",
                )
            )
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    from app.rag.retrieval_candidate_cache import clear_inflight_retrieval_candidates

    clear_inflight_retrieval_candidates()
    try:
        leader_thread = threading.Thread(target=_run)
        follower_thread = threading.Thread(target=_run)
        leader_thread.start()
        assert search_started.wait(timeout=1.0) is True
        follower_thread.start()
        leader_thread.join(timeout=2.0)
        follower_thread.join(timeout=2.0)
    finally:
        clear_inflight_retrieval_candidates()

    assert failures == []
    assert len(outputs) == 2
    assert outputs[0] == outputs[1]
    assert outputs[0][0]["content"] == "local future survives"


def test_query_debug_includes_singleflight_cache_role_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )

    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005,E501

    def _hybrid(self, query: str, **kwargs):  # noqa: ANN001,ARG002
        self._last_channel_metrics = {
            "cache": {
                "singleflight_role": "follower",
                "distributed_singleflight_hit": True,
            }
        }
        return []

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _hybrid, raising=True)

    retriever = HybridRetriever(
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        dataset_id=uuid.uuid4(),
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    assert retriever._get_relevant_documents("debug cache", run_manager=None) == []
    assert retriever._last_debug_metrics["channels"]["cache"]["singleflight_role"] == "follower"
    assert retriever._last_debug_metrics["channels"]["cache"]["distributed_singleflight_hit"] is True
