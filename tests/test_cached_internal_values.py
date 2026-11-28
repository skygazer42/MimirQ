from types import SimpleNamespace
from uuid import uuid4

import pytest


class _GroupQuery:
    def __init__(self, group_ids):
        self.group_ids = group_ids

    def filter(self, *_conditions):
        return self

    def all(self):
        return [(group_id,) for group_id in self.group_ids]


def test_request_group_cache_preserves_empty_results_and_scope_keys(monkeypatch):
    import app.services.identity.groups as service

    state = SimpleNamespace()
    monkeypatch.setattr(service, "get_request_state", lambda: state)
    tenant_id, other_tenant_id, group_id = uuid4(), uuid4(), uuid4()
    rows = [[], [group_id], []]
    calls = []

    class Database:
        def query(self, *_fields):
            calls.append(True)
            return _GroupQuery(rows[len(calls) - 1])

    db = Database()
    first = service.resolve_account_group_ids(db, tenant_id=tenant_id, account_id="first")
    assert first == set()
    assert service.resolve_account_group_ids(db, tenant_id=tenant_id, account_id="first") is first
    second = service.resolve_account_group_ids(db, tenant_id=tenant_id, account_id="second")
    assert second == {group_id}
    assert service.resolve_account_group_ids(db, tenant_id=other_tenant_id, account_id="first") == set()
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_chat_cache_getter_owns_json_object_validation(monkeypatch):
    import app.services.chat.response_cache as service

    monkeypatch.setattr(service.settings, "CHAT_RESPONSE_CACHE_ENABLED", True)

    async def decoded_array(_key):
        return []

    monkeypatch.setattr(service, "get_best_effort_json_cache_value", decoded_array)
    assert await service.get_cached_chat_response_async("key") is None


@pytest.mark.asyncio
async def test_chat_cache_reader_preserves_nested_payload_validation(monkeypatch):
    import app.services.chat.cache_flow as runtime
    import app.services.chat.response_cache as service

    monkeypatch.setattr(service.settings, "CHAT_RESPONSE_CACHE_ENABLED", True)
    async def lookup_cache(_work, *, request_db):
        return True, "key", None

    monkeypatch.setattr(runtime, "run_blocking_call_with_managed_session", lookup_cache)

    async def decoded_payload(_key):
        return {"content": "cached answer", "metrics": {}, "citations": "invalid nested citations"}

    monkeypatch.setattr(service, "get_best_effort_json_cache_value", decoded_payload)
    prepared = await runtime.prepare_non_streaming_chat_cache_state(options=SimpleNamespace(db=object()))
    assert prepared.cache_hit is True
    assert prepared.full_response == "cached answer"
    assert prepared.citations_data == []


def test_retrieval_cache_reuses_empty_hit_and_falls_back_only_on_absence(monkeypatch):
    import app.rag.retrieval.cache.candidates as cache

    empty_hit = []
    shared = [{"chunk_id": "shared"}]
    shared_reads = []
    monkeypatch.setattr(cache, "get_cached_retrieval_candidates", lambda _key: empty_hit)
    monkeypatch.setattr(
        cache,
        "get_distributed_inflight_retrieval_candidates",
        lambda key: shared_reads.append(key) or shared,
    )
    assert cache._read_any_distributed_retrieval_candidates("key") is empty_hit
    assert shared_reads == []
    monkeypatch.setattr(cache, "get_cached_retrieval_candidates", lambda _key: None)
    assert cache._read_any_distributed_retrieval_candidates("key") is shared
    assert shared_reads == ["key"]
