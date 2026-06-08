from __future__ import annotations

import uuid

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_kg_search_includes_query_mode_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", False, raising=False)

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
            return {
                "events": [],
                "entities": [],
                "stats": {
                    "query_mode": str(query_mode or ""),
                },
            }

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    out = await kgpipe.kg_search(
        query="overall trend of incidents",
        tenant_id=uuid.uuid4(),
        document_ids=[uuid.uuid4()],
        account_id="u",
        query_mode="global",
    )
    diag = out.get("query_mode") if isinstance(out, dict) else {}
    diag = diag if isinstance(diag, dict) else {}
    assert diag.get("requested") == "global"
    assert diag.get("resolved") == "global"
    stats = out.get("stats") if isinstance(out, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    assert stats.get("query_mode") == "global"


@pytest.mark.asyncio
async def test_kg_search_fans_out_multi_dataset_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.pipeline as kgpipe
    from app.core.config import settings

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_CACHE_ENABLED", False, raising=False)

    calls: list[uuid.UUID] = []

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
            assert query
            assert tenant_id is not None
            assert document_ids is None
            assert dataset_id is not None
            assert account_id == "u"
            calls.append(dataset_id)
            return {
                "events": [{"id": str(dataset_id), "chunk_id": str(uuid.uuid4()), "score": 0.7}],
                "entities": [{"entity_id": str(dataset_id), "name": f"dataset-{dataset_id}", "weight": 0.8}],
                "clues": [{"dataset_id": str(dataset_id)}],
                "stats": {"query_mode": str(query_mode or "")},
            }

    monkeypatch.setattr(kgpipe, "_load_engine", lambda: _FakeEngine(), raising=True)

    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    out = await kgpipe.kg_search(
        query="跨库问题",
        tenant_id=uuid.uuid4(),
        dataset_ids=[dataset_a, dataset_b, dataset_a],
        account_id="u",
        query_mode="global",
    )

    assert calls == [dataset_a, dataset_b]
    assert [item["id"] for item in out["events"]] == [str(dataset_a), str(dataset_b)]
    assert len(out["entities"]) == 2
    assert len(out["clues"]) == 2
    assert out["stats"]["multi_dataset_scope"] is True
    assert out["stats"]["dataset_shards"] == 2
    assert out["stats"]["dataset_shards_with_events"] == 2
