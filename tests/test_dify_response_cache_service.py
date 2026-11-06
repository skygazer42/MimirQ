import asyncio
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


def _records():
    return [{"content": "evidence", "score": 0.9, "title": "source", "metadata": {}}]


@pytest.fixture
def cache_backend(monkeypatch: pytest.MonkeyPatch):
    from app.services import chat_response_cache
    from app.services.dify_integration import response_cache

    values: dict[str, dict] = {}

    async def read(key):
        return values.get(key)

    async def write(key, payload, **_kwargs):
        values[key] = payload
        return True

    async def no_distributed_lease(*_args, **_kwargs):
        return None

    response_cache._clear_dify_response_cache()
    chat_response_cache.clear_inflight_chat_responses()
    monkeypatch.setattr(response_cache, "get_best_effort_json_cache_value", read)
    monkeypatch.setattr(response_cache, "set_best_effort_json_cache_value", write)
    monkeypatch.setattr(response_cache, "try_acquire_best_effort_redis_lease", no_distributed_lease)
    return response_cache, values


def _policy(cache):
    return cache.ResponseCachePolicy(ttl_sec=60, max_entries=32, response_cache_enabled=True, singleflight_enabled=True)


def test_dify_corpus_cache_token_uses_the_shared_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import corpus_cache_tokens
    from app.services.dify_integration import response_cache

    tenant_id, dataset_a, dataset_b = uuid4(), uuid4(), uuid4()
    database = object()
    seen = {}

    def resolve(db, **kwargs):
        assert db is database
        seen.update(kwargs)
        return "pipeline-v2"

    monkeypatch.setattr(corpus_cache_tokens, "resolve_corpus_cache_token", resolve)
    assert (
        response_cache._resolve_dify_response_cache_corpus_token(
            db=database, tenant_id=tenant_id, dataset_ids=[dataset_a, dataset_a, dataset_b]
        )
        == "pipeline-v2"
    )
    assert seen == {"tenant_id": tenant_id, "dataset_ids": [dataset_a, dataset_b]}


@pytest.mark.asyncio
async def test_response_cache_computes_once_and_reuses_records(cache_backend) -> None:
    cache, _values = cache_backend
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return _records()

    first = await cache.get_or_compute_response(key="cache-test", compute=compute, policy=_policy(cache))
    second = await cache.get_or_compute_response(key="cache-test", compute=compute, policy=_policy(cache))

    assert first.source == "computed"
    assert second.source == "cache_hit"
    assert first.records == second.records == _records()
    assert calls == 1


@pytest.mark.asyncio
async def test_local_follower_receives_records_before_redis_publication(
    cache_backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache, _values = cache_backend
    compute_started, finish_compute = asyncio.Event(), asyncio.Event()
    write_started, finish_write = asyncio.Event(), asyncio.Event()

    async def compute():
        compute_started.set()
        await finish_compute.wait()
        return _records()

    async def write(*_args, **_kwargs):
        write_started.set()
        await finish_write.wait()
        return True

    monkeypatch.setattr(cache, "_set_dify_response_cache_redis_payload", write)
    leader = asyncio.create_task(
        cache.get_or_compute_response(key="publication", compute=compute, policy=_policy(cache))
    )
    await compute_started.wait()
    follower = asyncio.create_task(
        cache.get_or_compute_response(key="publication", compute=compute, policy=_policy(cache))
    )
    await asyncio.sleep(0)
    finish_compute.set()
    try:
        await asyncio.wait_for(write_started.wait(), timeout=1)
        result = await asyncio.wait_for(follower, timeout=1)
        assert result.source == "singleflight_hit"
        assert result.records == _records()
        assert not leader.done()
    finally:
        finish_write.set()
        await leader


@pytest.mark.asyncio
async def test_failed_distributed_wait_releases_the_owned_local_flight(
    cache_backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import chat_response_cache

    cache, _values = cache_backend
    failure = RuntimeError("lease wait failed")

    async def fail_wait(*_args, **_kwargs):
        raise failure

    async def compute():
        pytest.fail("a failed lease wait must not start retrieval")

    monkeypatch.setattr(cache, "_acquire_or_wait_for_distributed_dify_response", fail_wait)
    with pytest.raises(RuntimeError, match="lease wait failed") as result:
        await cache.get_or_compute_response(key="failed-wait", compute=compute, policy=_policy(cache))
    assert result.value is failure
    leader, _future = await chat_response_cache.acquire_inflight_chat_response("failed-wait")
    assert leader is True
    chat_response_cache.resolve_inflight_chat_response("failed-wait", {"records": []})


@pytest.mark.asyncio
async def test_valid_empty_cached_records_are_a_hit(cache_backend) -> None:
    cache, values = cache_backend
    values["empty-result"] = {"schema": cache._DIFY_RESPONSE_CACHE_REDIS_SCHEMA, "records": []}

    async def compute():
        pytest.fail("a valid empty cache result must not be recomputed")

    result = await cache.get_or_compute_response(key="empty-result", compute=compute, policy=_policy(cache))
    assert result.source == "cache_hit"
    assert result.records == []


@pytest.mark.asyncio
@pytest.mark.parametrize("records", [[42], [{"content": "missing fields"}], [_records()[0], "invalid"]])
async def test_invalid_redis_records_are_a_cache_miss(monkeypatch: pytest.MonkeyPatch, records) -> None:
    from app.services.dify_integration import response_cache as cache

    async def read(_key):
        return {"schema": cache._DIFY_RESPONSE_CACHE_REDIS_SCHEMA, "records": records}

    monkeypatch.setattr(cache, "get_best_effort_json_cache_value", read)
    assert await cache._dify_response_cache_redis_payload("corrupt-cache") is None


def test_response_cache_executes_without_api_imports() -> None:
    code = """
import asyncio
import importlib.abc
import sys

attempts = []
class NoApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api' or fullname.startswith('app.api.'):
            attempts.append(fullname)
            raise AssertionError(fullname)

sys.meta_path.insert(0, NoApi())
from app.services.dify_integration import response_cache
async def compute():
    return [{'content': 'evidence', 'score': 0.9, 'title': 'source', 'metadata': {}}]
result = asyncio.run(response_cache.get_or_compute_response(
    key=None, compute=compute, policy=response_cache.resolve_policy(),
))
assert result.source == 'computed'
assert result.records[0]['content'] == 'evidence'
assert not attempts, attempts
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
