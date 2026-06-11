from __future__ import annotations

import asyncio
import uuid

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_kg_search_cache_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    # Best-effort reset between tests (no-op until implemented).
    reset_cache = getattr(kgpipe, "reset_kg_search_cache", None)
    if callable(reset_cache):
        reset_cache()

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(kgpipe, "_resolve_doc_pipeline_fingerprint", lambda *_a, **_k: "fp", raising=False)

    calls = {"n": 0}

    class _FakeEngine:
        async def search(  # noqa: ANN202
            self,
            *,
            query: str,
            tenant_id=None,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            query_mode=None,
            query_mode_reason_codes=None,
            query_mode_confidence=None,
        ):
            await yield_control()
            calls["n"] += 1
            return {"ok": True, "call": int(calls["n"]), "query": str(query or "")[:10]}

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    out1 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        document_ids=[doc_id],
        dataset_id=None,
        account_id="u",
    )
    out2 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        document_ids=[doc_id],
        dataset_id=None,
        account_id="u",
    )

    assert calls["n"] == 1
    assert out1["call"] == 1
    assert out2["call"] == 1


@pytest.mark.asyncio
async def test_kg_search_cache_hits_dataset_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    reset_cache = getattr(kgpipe, "reset_kg_search_cache", None)
    if callable(reset_cache):
        reset_cache()

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(kgpipe, "_resolve_dataset_pipeline_fingerprint", lambda *_a, **_k: "ds-fp", raising=False)

    calls = {"n": 0}

    class _FakeEngine:
        async def search(  # noqa: ANN202
            self,
            *,
            query: str,
            tenant_id=None,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            query_mode=None,
            query_mode_reason_codes=None,
            query_mode_confidence=None,
        ):
            await yield_control()
            calls["n"] += 1
            return {
                "ok": True,
                "call": int(calls["n"]),
                "query": str(query or "")[:10],
                "dataset_id": str(dataset_id or ""),
            }

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    out1 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        account_id="u",
    )
    out2 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        account_id="u",
    )

    assert calls["n"] == 1
    assert out1["call"] == 1
    assert out2["call"] == 1


@pytest.mark.asyncio
async def test_kg_search_cache_separates_account_and_doc_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    reset_cache = getattr(kgpipe, "reset_kg_search_cache", None)
    if callable(reset_cache):
        reset_cache()

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(kgpipe, "_resolve_doc_pipeline_fingerprint", lambda *_a, **_k: "fp", raising=False)

    calls = {"n": 0}

    class _FakeEngine:
        async def search(  # noqa: ANN202
            self,
            *,
            query: str,
            tenant_id=None,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            query_mode=None,
            query_mode_reason_codes=None,
            query_mode_confidence=None,
        ):
            await yield_control()
            calls["n"] += 1
            return {
                "ok": True,
                "call": int(calls["n"]),
                "account_id": str(account_id or ""),
                "doc_count": int(len(document_ids or [])),
            }

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    tenant_id = uuid.uuid4()
    doc_a = uuid.uuid4()
    doc_b = uuid.uuid4()

    # First scope.
    out1 = await kgpipe.kg_search(query="q", tenant_id=tenant_id, document_ids=[doc_a], account_id="u1")
    assert out1["call"] == 1

    # Different account_id must not hit the cache (ACL-safe).
    out2 = await kgpipe.kg_search(query="q", tenant_id=tenant_id, document_ids=[doc_a], account_id="u2")
    assert out2["call"] == 2

    # Different doc scope must not hit the cache.
    out3 = await kgpipe.kg_search(query="q", tenant_id=tenant_id, document_ids=[doc_b], account_id="u1")
    assert out3["call"] == 3

    # Original scope should still be cached.
    out4 = await kgpipe.kg_search(query="q", tenant_id=tenant_id, document_ids=[doc_a], account_id="u1")
    assert out4["call"] == 1

    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_kg_search_cache_invalidates_on_active_pipeline_hash_change(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    reset_cache = getattr(kgpipe, "reset_kg_search_cache", None)
    if callable(reset_cache):
        reset_cache()

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_MAX_ENTRIES", 32, raising=False)

    calls = {"n": 0}

    class _FakeEngine:
        async def search(  # noqa: ANN202
            self,
            *,
            query: str,
            tenant_id=None,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            query_mode=None,
            query_mode_reason_codes=None,
            query_mode_confidence=None,
        ):
            await yield_control()
            calls["n"] += 1
            return {"ok": True, "call": int(calls["n"]), "query": str(query or "")[:10]}

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    # Simulate a document switching active_pipeline_hash between otherwise identical calls.
    # The cache key must include a pipeline fingerprint, so this change should miss the cache.
    fp_calls = {"n": 0}

    def _fake_pipeline_fp(*_a, **_k) -> str:  # noqa: ANN001
        fp_calls["n"] += 1
        return "fp_v1" if fp_calls["n"] == 1 else "fp_v2"

    monkeypatch.setattr(kgpipe, "_resolve_doc_pipeline_fingerprint", _fake_pipeline_fp, raising=False)

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    out1 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        document_ids=[doc_id],
        dataset_id=None,
        account_id="u",
    )
    out2 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        document_ids=[doc_id],
        dataset_id=None,
        account_id="u",
    )

    assert out1["call"] == 1
    assert out2["call"] == 2
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_kg_search_cache_separates_query_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    reset_cache = getattr(kgpipe, "reset_kg_search_cache", None)
    if callable(reset_cache):
        reset_cache()

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_MAX_ENTRIES", 32, raising=False)
    monkeypatch.setattr(kgpipe, "_resolve_doc_pipeline_fingerprint", lambda *_a, **_k: "fp", raising=False)

    calls = {"n": 0}

    class _FakeEngine:
        async def search(  # noqa: ANN202
            self,
            *,
            query: str,
            tenant_id=None,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            query_mode=None,
            query_mode_reason_codes=None,
            query_mode_confidence=None,
        ):
            await yield_control()
            calls["n"] += 1
            return {"ok": True, "call": int(calls["n"]), "query_mode": str(query_mode or "")}

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    out1 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        document_ids=[doc_id],
        account_id="u",
        query_mode="local",
    )
    out2 = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        document_ids=[doc_id],
        account_id="u",
        query_mode="global",
    )

    assert out1["call"] == 1
    assert out2["call"] == 2
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_kg_search_multi_dataset_scope_runs_bounded_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_MULTI_DATASET_MAX_CONCURRENCY", 2, raising=False)

    active = {"n": 0, "max": 0}
    calls: list[str] = []

    class _FakeEngine:
        async def search(  # noqa: ANN202
            self,
            *,
            query: str,
            tenant_id=None,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            query_mode=None,
            query_mode_reason_codes=None,
            query_mode_confidence=None,
        ):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            calls.append(str(dataset_id or ""))
            try:
                await asyncio.sleep(0.01)
                return {
                    "events": [{"id": str(dataset_id), "score": 1.0}],
                    "entities": [],
                    "clues": [],
                    "stats": {"query_mode": str(query_mode or "")},
                }
            finally:
                active["n"] -= 1

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    tenant_id = uuid.uuid4()
    dataset_ids = [uuid.uuid4() for _ in range(5)]

    out = await kgpipe.kg_search(
        query="q",
        tenant_id=tenant_id,
        dataset_ids=dataset_ids,
        account_id="u",
    )

    assert sorted(calls) == sorted(str(dataset_id) for dataset_id in dataset_ids)
    assert active["max"] == 2
    assert out["stats"]["multi_dataset_scope"] is True
    assert out["stats"]["dataset_shards"] == 5
    assert len(out["events"]) == 5
