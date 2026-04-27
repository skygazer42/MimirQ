from __future__ import annotations


def _sample_reports() -> list[dict[str, object]]:
    return [
        {"community_id": "c0", "community_level": 0, "score": 0.6, "entity_count": 30, "event_count": 12},
        {"community_id": "c1", "community_level": 1, "score": 0.7, "entity_count": 18, "event_count": 8},
        {"community_id": "c2a", "community_level": 2, "score": 0.95, "entity_count": 8, "event_count": 5},
        {"community_id": "c2b", "community_level": 2, "score": 0.8, "entity_count": 7, "event_count": 4},
    ]


def test_build_multi_level_community_selection_prefers_coarse_reports_for_global_scope() -> None:
    from app.rag.kg.community import build_multi_level_community_selection

    out = build_multi_level_community_selection(
        reports=_sample_reports(),
        query_scope="global",
        max_reports=2,
    )

    assert out["schema"] == "mimirq.kg_community_selection.v1"
    assert out["query_scope"] == "global"
    assert out["levels_present"] == [0, 1, 2]
    assert [row["community_id"] for row in out["selected_reports"]] == ["c0", "c1"]


def test_build_multi_level_community_selection_prefers_deep_reports_for_local_scope() -> None:
    from app.rag.kg.community import build_multi_level_community_selection

    out = build_multi_level_community_selection(
        reports=_sample_reports(),
        query_scope="local",
        max_reports=2,
    )

    assert out["query_scope"] == "local"
    assert [row["community_id"] for row in out["selected_reports"]] == ["c2a", "c2b"]


def test_build_multi_level_community_selection_blends_coarse_and_deep_reports_for_drift_scope() -> None:
    from app.rag.kg.community import build_multi_level_community_selection

    out = build_multi_level_community_selection(
        reports=_sample_reports(),
        query_scope="drift",
        max_reports=3,
    )

    assert out["query_scope"] == "drift"
    assert [row["community_id"] for row in out["selected_reports"]] == ["c0", "c2a", "c2b"]
