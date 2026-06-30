from __future__ import annotations


def test_clause_fastlane_queries_include_refs() -> None:
    from app.rag.policy.query_expansion import build_clause_fastlane_queries

    q = "按第十二条说明例外"
    extra = build_clause_fastlane_queries(q)
    assert any("第十二条" in x for x in extra)


def test_lightweight_subquery_queries_split_multi_intent_cjk_question() -> None:
    from app.rag.policy.query_expansion import build_lightweight_subquery_queries

    extra = build_lightweight_subquery_queries(
        "我身份证快到期了，顺便想知道如果丢了怎么处理、怎么查办理进度、怎么领取电子身份证，请给我一份完整办理指引。",
        max_queries=3,
    )

    assert 1 <= len(extra) <= 3
    assert any("身份证快到期" in item for item in extra)
    assert any("办理进度" in item or "电子身份证" in item for item in extra)


def test_lightweight_subquery_queries_skip_short_single_intent_question() -> None:
    from app.rag.policy.query_expansion import build_lightweight_subquery_queries

    assert build_lightweight_subquery_queries("身份证怎么办？") == []
