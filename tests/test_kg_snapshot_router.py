from __future__ import annotations


def test_route_snapshot_for_query_selects_matching_year_snapshot() -> None:
    from app.rag.kg.search.snapshot_router import route_snapshot_for_query

    out = route_snapshot_for_query(
        query="X 在 2024 年是什么状态？",
        available_snapshots=["2023-12", "2024-06", "2025-01"],
    )

    assert out["selected_snapshot"] == "2024-06"
    assert out["temporal_query"] is True
    assert "year_match" in out["reason_codes"]


def test_route_snapshot_for_query_prefers_latest_for_current_queries() -> None:
    from app.rag.kg.search.snapshot_router import route_snapshot_for_query

    out = route_snapshot_for_query(
        query="当前整体情况是什么？",
        available_snapshots=["2024-06", "2025-01"],
    )

    assert out["selected_snapshot"] == "2025-01"
    assert out["temporal_query"] is True
    assert "latest_keyword" in out["reason_codes"]


def test_route_snapshot_for_query_noops_when_query_is_not_temporal() -> None:
    from app.rag.kg.search.snapshot_router import route_snapshot_for_query

    out = route_snapshot_for_query(
        query="系统有哪些核心模块？",
        available_snapshots=["2024-06", "2025-01"],
    )

    assert out["selected_snapshot"] is None
    assert out["temporal_query"] is False
