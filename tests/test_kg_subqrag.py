from __future__ import annotations


def test_build_subqrag_plan_decomposes_and_routes_each_subquery() -> None:
    from app.rag.kg.search.subqrag import build_subqrag_plan

    out = build_subqrag_plan("Find ACME subsidiaries and explain why revenue changed across regions")

    assert out["planner"] == "deterministic_subqrag_proxy"
    assert out["requires_fusion"] is True
    assert [row["query"] for row in out["subqueries"]] == [
        "Find ACME subsidiaries",
        "explain why revenue changed across regions",
    ]
    assert [row["method"] for row in out["subqueries"]] == ["hybrid", "drift_search"]
    assert out["subqueries"][1]["reason_codes"] == ["kg_mode_drift"]


def test_build_subqrag_plan_falls_back_to_root_query_when_no_split_is_available() -> None:
    from app.rag.kg.search.subqrag import build_subqrag_plan

    out = build_subqrag_plan("整体有哪些核心模块？")

    assert out["requires_fusion"] is False
    assert len(out["subqueries"]) == 1
    assert out["subqueries"][0]["query"] == "整体有哪些核心模块？"
    assert out["subqueries"][0]["method"] == "hybrid"
