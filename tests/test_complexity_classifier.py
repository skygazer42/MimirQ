from __future__ import annotations

from app.rag.policy.complexity_classifier import classify_query_complexity


def test_classify_query_complexity_distinguishes_simple_structured_and_multi_hop() -> None:
    simple = classify_query_complexity("485 怎么配置？")
    structured = classify_query_complexity("查询 X9 设备的通信波特率字段在哪个 schema 节点？")
    multi = classify_query_complexity("根据报警日志和设备状态，为什么 485 会掉线？")

    assert simple["label"] == "simple"
    assert structured["label"] == "structured"
    assert multi["label"] == "multi_hop"
