from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForRetrieverRun


def test_retrieval_hierarchy_family_fixture_contract_v1() -> None:
    payload = json.loads(Path("ci/retrieval_hierarchy_family_fixture.v1.json").read_text(encoding="utf-8"))
    assert str(payload.get("schema") or "") == "mimirq.retrieval_hierarchy_family_fixture.v1"
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    assert cases

    c0 = cases[0]
    assert str(c0.get("id") or "")
    assert str(c0.get("retrieval_profile") or "")
    assert int(c0.get("requested_k") or 0) > 0
    expected = c0.get("expected") if isinstance(c0.get("expected"), dict) else {}
    assert int(expected.get("search_k") or 0) > 0
    assert list(expected.get("visible_chunk_ids") or [])
    assert list(expected.get("visible_family_keys") or [])


def test_hierarchy_family_fixture_replays_visible_results(monkeypatch) -> None:  # noqa: ANN001
    from app.rag.retriever import HybridRetriever

    payload = json.loads(Path("ci/retrieval_hierarchy_family_fixture.v1.json").read_text(encoding="utf-8"))
    case = payload["cases"][0]
    results = list(case["results"])
    expected = case["expected"]

    monkeypatch.setattr(
        HybridRetriever,
        "_enrich_results_with_db_metadata",
        lambda self, items, stats=None: list(items),
        raising=True,
    )
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items), raising=True)
    monkeypatch.setattr(HybridRetriever, "_apply_governance_policy", lambda self, items, stats=None: list(items), raising=True)

    def _fake_hybrid_search(self, *, query: str, top_k: int, **_kw):  # noqa: ANN001
        assert top_k == int(expected["search_k"])
        return list(results)

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    retriever = HybridRetriever(
        k=int(case["requested_k"]),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        retrieval_profile=str(case["retrieval_profile"]),
        enable_hierarchy_recall=True,
        hierarchy_family_collapse=True,
        hierarchy_overfetch_factor=int(case["hierarchy_overfetch_factor"]),
    )

    docs = retriever._get_relevant_documents("q", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    assert [doc.id for doc in docs] == list(expected["visible_chunk_ids"])
    assert [doc.metadata.get("hierarchy_family_key") for doc in docs] == list(expected["visible_family_keys"])
