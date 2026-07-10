
from app.rag.kg.search.lazy_indexer import build_lazy_index_plan


def test_build_lazy_index_plan_selects_only_missing_hit_communities() -> None:
    out = build_lazy_index_plan(
        hit_community_ids=["c3", "c1", "c2", "c3"],
        indexed_community_ids=["c1"],
        max_new_communities=2,
    )

    assert out["schema"] == "mimirq.kg_lazy_index_plan.v1"
    assert out["hit_communities"] == ["c1", "c2", "c3"]
    assert out["deferred_communities"] == ["c2", "c3"]
    assert out["reason_codes"] == ["build_missing_hit_communities"]


def test_build_lazy_index_plan_returns_no_work_when_everything_is_indexed() -> None:
    out = build_lazy_index_plan(
        hit_community_ids=["c1", "c2"],
        indexed_community_ids=["c1", "c2"],
        max_new_communities=3,
    )

    assert out["deferred_communities"] == []
    assert out["reason_codes"] == ["all_hit_communities_indexed"]
