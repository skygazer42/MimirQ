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

    def eval(self, _script: str, _numkeys: int, key: str, value: str) -> int:
        self._purge_expired(key)
        current = self._values.get(key)
        if isinstance(current, bytes):
            current = current.decode("utf-8", "ignore")
        if current != value:
            return 0
        self._values.pop(key, None)
        self._expires_at.pop(key, None)
        return 1


def _patch_fake_candidate_redis(monkeypatch: pytest.MonkeyPatch, cache_mod, redis: _FakeRedis) -> None:  # noqa: ANN001
    monkeypatch.setattr(cache_mod, "_get_redis_client", lambda: redis, raising=True)
    monkeypatch.setattr(cache_mod, "_invalidate_redis_client", lambda: None, raising=True)
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


def test_distributed_retrieval_singleflight_wait_uses_admission_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval_candidate_cache as cache_mod

    redis = _FakeRedis()
    _patch_fake_candidate_redis(monkeypatch, cache_mod, redis)
    monkeypatch.setattr(cache_mod.settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 2.0, raising=False)
    clock = [0.0]
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock[0], raising=True)
    monkeypatch.setattr(cache_mod.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay), raising=True)

    leader, _payload, lease = cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("bounded-wait")
    assert leader is True
    assert lease is not None

    follower_leader, follower_payload, follower_lease = (
        cache_mod.acquire_or_wait_for_distributed_inflight_retrieval_candidates("bounded-wait")
    )

    assert follower_leader is True
    assert follower_payload is None
    assert follower_lease is None
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
