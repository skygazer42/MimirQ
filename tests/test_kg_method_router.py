from __future__ import annotations


def test_route_kg_search_method_uses_pprank_for_structured_local_queries() -> None:
    from app.rag.kg.search.method_router import route_kg_search_method

    out = route_kg_search_method("查询 X9 设备的通信波特率字段在哪个 schema 节点？")

    assert out["method"] == "pprank"
    assert out["complexity"]["label"] == "structured"


def test_route_kg_search_method_uses_drift_for_multi_hop_change_queries() -> None:
    from app.rag.kg.search.method_router import route_kg_search_method

    out = route_kg_search_method("Compare revenue drift across regions and explain why it changed")

    assert out["method"] == "drift_search"
    assert out["complexity"]["label"] == "multi_hop"
    assert out["kg_mode"]["mode"] == "drift"


def test_route_kg_search_method_falls_back_to_hybrid_for_simple_global_queries() -> None:
    from app.rag.kg.search.method_router import route_kg_search_method

    out = route_kg_search_method("整体有哪些核心模块？")

    assert out["method"] == "hybrid"
