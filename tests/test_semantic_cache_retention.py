import json
import time
import uuid

import pytest


def _configure_semantic_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_SCORE_THRESHOLD", 0.95, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_SEARCH_TOP_K", 5, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_REDIS_PREFIX", "semc", raising=False)


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1, 0.2]


class _FakeRedis:
    def __init__(self, values: dict[str, bytes | None]) -> None:
        self.values = dict(values)
        self.get_calls: list[str] = []

    def get(self, key: str) -> bytes | None:
        self.get_calls.append(key)
        return self.values.get(key)


class _FakeMaintenanceIterator:
    def __init__(
        self,
        *,
        pages: list[list[dict]],
        error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.pages = [list(page) for page in pages]
        self.error = error
        self.close_error = close_error
        self.index = 0
        self.closed = False

    def next(self) -> list[dict]:
        if self.error is not None:
            raise self.error
        if self.index >= len(self.pages):
            return []
        page = self.pages[self.index]
        self.index += 1
        return list(page)

    def next_batch(self) -> list[dict]:
        return self.next()

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakeAdapter:
    def __init__(
        self,
        *,
        search_results: list[dict] | None = None,
        sweep_pages: list[list[dict]] | None = None,
        sweep_error: Exception | None = None,
    ) -> None:
        self.search_results = list(search_results or [])
        self.sweep_pages = [list(page) for page in (sweep_pages or [])]
        self.sweep_error = sweep_error
        self.sweep_close_error: Exception | None = None
        self.deleted_batches: list[list[str]] = []
        self.batch_sizes: list[int] = []
        self.list_tenant_ids: list[str | None] = []
        self.maintenance_iterators: list[_FakeMaintenanceIterator] = []

    def search(self, *_args, **_kwargs) -> list[dict]:
        return list(self.search_results)

    def delete(self, ids: list[str]) -> None:
        self.deleted_batches.append(list(ids))

    def open_semantic_cache_maintenance_iterator(self, *, tenant_id=None, batch_size=0, timeout=None):  # noqa: ANN001,ANN202,ARG002
        if self.sweep_error is not None:
            raise self.sweep_error
        self.list_tenant_ids.append(None if tenant_id is None else str(tenant_id))
        batch_size_i = max(1, int(batch_size))
        self.batch_sizes.append(batch_size_i)
        batches: list[list[dict]] = []
        for page in self.sweep_pages:
            if len(page) <= batch_size_i:
                batches.append(list(page))
                continue
            for start in range(0, len(page), batch_size_i):
                batches.append(list(page[start : start + batch_size_i]))
        iterator = _FakeMaintenanceIterator(
            pages=batches,
            close_error=self.sweep_close_error,
        )
        self.maintenance_iterators.append(iterator)
        return iterator


def test_semantic_cache_lookup_skips_expired_vector_before_redis_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache

    _configure_semantic_cache(monkeypatch)
    now_epoch = int(time.time())
    adapter = _FakeAdapter(
        search_results=[
            {
                "id": "vec-expired",
                "score": 0.99,
                "metadata": {
                    "tenant_id": "tenant-1",
                    "account_id": "account-1",
                    "scope_hash": "scope-1",
                    "corpus_cache_token": "corpus-1",
                    "embedding_space_hash": "space-1",
                    "expires_at_epoch": now_epoch - 1,
                },
            }
        ]
    )
    redis_client = _FakeRedis({})
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_embeddings", lambda: _FakeEmbeddings(), raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: redis_client, raising=True)
    monkeypatch.setattr(semantic_cache, "current_embedding_space_hash", lambda: "space-1", raising=True)
    monkeypatch.setattr(
        semantic_cache,
        "build_semantic_cache_scope_hash",
        lambda **_kwargs: ("scope-1", "vec-expired"),
        raising=True,
    )

    payload, meta = semantic_cache.get_cached_semantic_payload(
        tenant_id="tenant-1",
        account_id="account-1",
        dataset_id="dataset-1",
        corpus_cache_token="corpus-1",
        query="expired query",
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        metadata_filter=None,
        document_ids=["doc-1"],
    )

    assert payload is None
    assert redis_client.get_calls == []
    assert adapter.deleted_batches == [["vec-expired"]]
    assert meta["expired_vectors_skipped"] == 1
    assert meta["cleanup_attempted"] == 1


def test_semantic_cache_lookup_bounds_orphan_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache

    _configure_semantic_cache(monkeypatch)
    monkeypatch.setattr(semantic_cache, "_LOOKUP_CLEANUP_MAX_DELETE", 2, raising=False)
    adapter = _FakeAdapter(
        search_results=[
            {
                "id": "vec-1",
                "score": 0.99,
                "metadata": {
                    "tenant_id": "tenant-1",
                    "account_id": "account-1",
                    "scope_hash": "scope-1",
                    "corpus_cache_token": "corpus-1",
                    "embedding_space_hash": "space-1",
                    "expires_at_epoch": int(time.time()) + 60,
                },
            },
            {
                "id": "vec-2",
                "score": 0.99,
                "metadata": {
                    "tenant_id": "tenant-1",
                    "account_id": "account-1",
                    "scope_hash": "scope-1",
                    "corpus_cache_token": "corpus-1",
                    "embedding_space_hash": "space-1",
                    "expires_at_epoch": int(time.time()) + 60,
                },
            },
            {
                "id": "vec-3",
                "score": 0.99,
                "metadata": {
                    "tenant_id": "tenant-1",
                    "account_id": "account-1",
                    "scope_hash": "scope-1",
                    "corpus_cache_token": "corpus-1",
                    "embedding_space_hash": "space-1",
                    "expires_at_epoch": int(time.time()) + 60,
                },
            },
        ]
    )
    redis_client = _FakeRedis({})
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_embeddings", lambda: _FakeEmbeddings(), raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: redis_client, raising=True)
    monkeypatch.setattr(semantic_cache, "current_embedding_space_hash", lambda: "space-1", raising=True)
    monkeypatch.setattr(
        semantic_cache,
        "build_semantic_cache_scope_hash",
        lambda **_kwargs: ("scope-1", "vec-1"),
        raising=True,
    )

    payload, meta = semantic_cache.get_cached_semantic_payload(
        tenant_id="tenant-1",
        account_id="account-1",
        dataset_id="dataset-1",
        corpus_cache_token="corpus-1",
        query="orphan query",
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        metadata_filter=None,
        document_ids=["doc-1"],
    )

    assert payload is None
    assert adapter.deleted_batches == [["vec-1", "vec-2"]]
    assert meta["orphan_vectors_skipped"] == 3
    assert meta["cleanup_attempted"] == 2


def test_semantic_cache_sweep_deletes_expired_and_legacy_orphans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache

    _configure_semantic_cache(monkeypatch)
    tenant_id = str(uuid.uuid4())
    adapter = _FakeAdapter(
        sweep_pages=[
            [
                {"id": "expired-1", "tenant_id": tenant_id, "expires_at_epoch": int(time.time()) - 5},
                {"id": "legacy-orphan", "tenant_id": tenant_id},
                {"id": "legacy-live", "tenant_id": tenant_id},
                {"id": "fresh-1", "tenant_id": tenant_id, "expires_at_epoch": int(time.time()) + 30},
            ]
        ]
    )
    redis_client = _FakeRedis(
        {
            semantic_cache._redis_payload_key(tenant_id=tenant_id, vector_id="legacy-live"): json.dumps(
                [{"id": 1}]
            ).encode("utf-8")
        }
    )
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: redis_client, raising=True)

    summary = semantic_cache.run_semantic_cache_retention(
        tenant_id=tenant_id,
        dry_run=False,
        max_delete=10,
        now_epoch=int(time.time()),
    )

    assert summary["eligible"] == 2
    assert summary["deleted"] == 2
    assert summary["expired_candidates"] == 1
    assert summary["legacy_orphan_candidates"] == 1
    assert summary["legacy_rows_preserved"] == 1
    assert summary["exhausted"] is True
    assert adapter.deleted_batches == [["expired-1", "legacy-orphan"]]


def test_semantic_cache_sweep_budget_caps_per_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache

    _configure_semantic_cache(monkeypatch)
    adapter = _FakeAdapter(
        sweep_pages=[
            [
                {"id": "expired-1", "tenant_id": "tenant-1", "expires_at_epoch": int(time.time()) - 5},
                {"id": "expired-2", "tenant_id": "tenant-1", "expires_at_epoch": int(time.time()) - 5},
                {"id": "expired-3", "tenant_id": "tenant-1", "expires_at_epoch": int(time.time()) - 5},
            ]
        ]
    )
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: _FakeRedis({}), raising=True)

    summary = semantic_cache.run_semantic_cache_retention(
        tenant_id="tenant-1",
        dry_run=False,
        max_delete=2,
        max_scan=5,
        now_epoch=int(time.time()),
    )

    assert adapter.batch_sizes == [2]
    assert summary["scanned"] == 2
    assert summary["deleted"] == 2
    assert adapter.deleted_batches == [["expired-1", "expired-2"]]
    assert adapter.maintenance_iterators[0].closed is True


def test_semantic_cache_sweep_continues_past_fresh_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache

    _configure_semantic_cache(monkeypatch)
    tenant_id = "tenant-1"
    adapter = _FakeAdapter(
        sweep_pages=[
            [
                {"id": "fresh-1", "tenant_id": tenant_id, "expires_at_epoch": int(time.time()) + 60},
                {"id": "fresh-2", "tenant_id": tenant_id, "expires_at_epoch": int(time.time()) + 60},
            ],
            [
                {"id": "expired-1", "tenant_id": tenant_id, "expires_at_epoch": int(time.time()) - 5},
                {"id": "legacy-orphan", "tenant_id": tenant_id},
            ],
        ]
    )
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: _FakeRedis({}), raising=True)

    summary = semantic_cache.run_semantic_cache_retention(
        tenant_id=tenant_id,
        dry_run=False,
        max_delete=2,
        max_scan=4,
        now_epoch=int(time.time()),
    )

    assert adapter.batch_sizes == [2]
    assert summary["scanned"] == 4
    assert summary["deleted"] == 2
    assert summary["expired_candidates"] == 1
    assert summary["legacy_orphan_candidates"] == 1
    assert adapter.deleted_batches == [["expired-1", "legacy-orphan"]]
    assert adapter.maintenance_iterators[0].closed is True


def test_semantic_cache_sweep_marks_scan_limit_when_not_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache

    _configure_semantic_cache(monkeypatch)
    adapter = _FakeAdapter(
        sweep_pages=[
            [{"id": "fresh-1", "tenant_id": "tenant-1", "expires_at_epoch": int(time.time()) + 60}],
            [{"id": "fresh-2", "tenant_id": "tenant-1", "expires_at_epoch": int(time.time()) + 60}],
            [{"id": "expired-1", "tenant_id": "tenant-1", "expires_at_epoch": int(time.time()) - 5}],
        ]
    )
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: _FakeRedis({}), raising=True)

    summary = semantic_cache.run_semantic_cache_retention(
        tenant_id="tenant-1",
        dry_run=True,
        max_delete=1,
        max_scan=2,
        now_epoch=int(time.time()),
    )

    assert summary["scanned"] == 2
    assert summary["scan_limit_reached"] is True
    assert summary["exhausted"] is False
    assert summary["eligible"] == 0
    assert adapter.maintenance_iterators[0].closed is True


def test_semantic_cache_sweep_reports_adapter_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache
    from app.storage.vector.milvus import MilvusMaintenanceError

    _configure_semantic_cache(monkeypatch)
    adapter = _FakeAdapter(sweep_error=MilvusMaintenanceError("missing tenant_id metadata"))
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)

    summary = semantic_cache.run_semantic_cache_retention(
        tenant_id="tenant-1",
        dry_run=False,
        max_delete=2,
        max_scan=4,
    )

    assert summary["failed"] is True
    assert summary["errors"] == ["missing tenant_id metadata"]
    assert summary["deleted"] == 0


def test_semantic_cache_sweep_reports_iterator_next_failure_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache
    from app.storage.vector.milvus import MilvusMaintenanceError

    _configure_semantic_cache(monkeypatch)
    adapter = _FakeAdapter()
    iterator = _FakeMaintenanceIterator(
        pages=[],
        error=MilvusMaintenanceError("iterator next failed"),
    )
    adapter.open_semantic_cache_maintenance_iterator = lambda **_kwargs: iterator  # type: ignore[method-assign]
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)

    summary = semantic_cache.run_semantic_cache_retention(
        tenant_id="tenant-1",
        dry_run=False,
        max_delete=2,
        max_scan=4,
    )

    assert summary["failed"] is True
    assert summary["errors"] == ["iterator next failed"]
    assert summary["deleted"] == 0
    assert iterator.closed is True


def test_semantic_cache_sweep_reports_iterator_close_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache
    from app.storage.vector.milvus import MilvusMaintenanceError

    _configure_semantic_cache(monkeypatch)
    adapter = _FakeAdapter(
        sweep_pages=[[{"id": "fresh-1", "tenant_id": "tenant-1", "expires_at_epoch": int(time.time()) + 60}]]
    )
    adapter.sweep_close_error = MilvusMaintenanceError("iterator close failed")
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: _FakeRedis({}), raising=True)

    summary = semantic_cache.run_semantic_cache_retention(
        tenant_id="tenant-1",
        dry_run=False,
        max_delete=1,
        max_scan=4,
    )

    assert summary["failed"] is True
    assert summary["errors"] == ["iterator close failed"]
    assert summary["deleted"] == 0


def test_legacy_semantic_cache_row_remains_readable_until_payload_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.semantic_cache as semantic_cache

    _configure_semantic_cache(monkeypatch)
    payload_bytes = json.dumps([{"chunk_id": "chunk-1"}]).encode("utf-8")
    adapter = _FakeAdapter(
        search_results=[
            {
                "id": "legacy-live",
                "score": 0.99,
                "metadata": {
                    "tenant_id": "tenant-1",
                    "account_id": "account-1",
                    "scope_hash": "scope-1",
                    "corpus_cache_token": "corpus-1",
                    "embedding_space_hash": "space-1",
                },
            }
        ]
    )
    redis_client = _FakeRedis({"semc:tenant-1:legacy-live": payload_bytes})
    monkeypatch.setattr(semantic_cache, "_get_adapter", lambda: adapter, raising=True)
    monkeypatch.setattr(semantic_cache, "_get_embeddings", lambda: _FakeEmbeddings(), raising=True)
    monkeypatch.setattr(semantic_cache, "_get_redis_client", lambda: redis_client, raising=True)
    monkeypatch.setattr(semantic_cache, "current_embedding_space_hash", lambda: "space-1", raising=True)
    monkeypatch.setattr(
        semantic_cache,
        "build_semantic_cache_scope_hash",
        lambda **_kwargs: ("scope-1", "legacy-live"),
        raising=True,
    )

    payload, meta = semantic_cache.get_cached_semantic_payload(
        tenant_id="tenant-1",
        account_id="account-1",
        dataset_id="dataset-1",
        corpus_cache_token="corpus-1",
        query="legacy query",
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        metadata_filter=None,
        document_ids=["doc-1"],
    )

    assert payload == [{"chunk_id": "chunk-1"}]
    assert meta["hit"] is True
    assert adapter.deleted_batches == []
