from __future__ import annotations


def test_extract_clause_refs_cn_article_and_clause() -> None:
    from app.rag.policy.clause_refs import extract_clause_refs

    q = "请按第十二条（3）说明例外条件"
    refs = extract_clause_refs(q)
    assert "第十二条" in refs
    assert "（3）" in refs


def test_extract_clause_refs_en_article_section() -> None:
    from app.rag.policy.clause_refs import extract_clause_refs

    q = "What does Article 7 say? See Section 3.2.1 for exceptions."
    refs = extract_clause_refs(q)
    assert "Article 7" in refs
    assert "Section 3.2.1" in refs


def test_normalize_clause_ref_is_stable_and_safe() -> None:
    from app.rag.policy.clause_refs import normalize_clause_ref

    assert normalize_clause_ref(" 第十二条 ") == "第十二条"
    assert normalize_clause_ref("SECTION 3.2.1") == "Section 3.2.1"

