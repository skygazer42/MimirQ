from __future__ import annotations


def test_clause_fastlane_queries_include_refs() -> None:
    from app.rag.policy.query_expansion import build_clause_fastlane_queries

    q = "按第十二条说明例外"
    extra = build_clause_fastlane_queries(q)
    assert any("第十二条" in x for x in extra)

