from __future__ import annotations

from app.rag.workflows.system_router import route_system_query


def test_route_system_query_maps_complexity_to_route_profiles() -> None:
    simple = route_system_query("485 怎么配置？")
    structured = route_system_query("查询 X9 设备的通信波特率字段在哪个 schema 节点？")
    multi = route_system_query("根据报警日志和设备状态，为什么 485 会掉线？")

    assert simple["route"] == "retrieval"
    assert simple["retrieval_profile"] == "hybrid_ce"
    assert structured["route"] == "kg"
    assert multi["route"] == "hybrid"
