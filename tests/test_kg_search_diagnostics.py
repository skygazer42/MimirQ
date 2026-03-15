from __future__ import annotations

import asyncio
import uuid

import pytest


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
            await asyncio.sleep(0)  # Sonar S7503
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
