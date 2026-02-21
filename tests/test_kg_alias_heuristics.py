from __future__ import annotations


def test_extract_alias_candidates_parentheses() -> None:
    from app.rag.kg.extraction.alias import extract_alias_candidates

    text = "We use Retrieval-Augmented Generation (RAG) in our system."
    out = extract_alias_candidates(text, max_candidates=10)
    assert any(c.a == "Retrieval-Augmented Generation" and c.b == "RAG" for c in out)


def test_choose_alias_direction_picks_abbrev() -> None:
    from app.rag.kg.extraction.alias import choose_alias_direction

    assert choose_alias_direction("Retrieval-Augmented Generation", "RAG") == ("RAG", "Retrieval-Augmented Generation")
    assert choose_alias_direction("RAG", "Retrieval-Augmented Generation") == ("RAG", "Retrieval-Augmented Generation")


def test_choose_alias_direction_ignores_versions() -> None:
    from app.rag.kg.extraction.alias import choose_alias_direction

    # Version-like tokens should not be treated as aliases.
    assert choose_alias_direction("Foo", "v2") is None
    assert choose_alias_direction("Foo", "2.0") is None


def test_extract_alias_candidates_zh_abbr() -> None:
    from app.rag.kg.extraction.alias import extract_alias_candidates

    text = "清华大学，简称清华，是国内知名高校。"
    out = extract_alias_candidates(text, max_candidates=10)
    assert any(c.a == "清华大学" and c.b == "清华" for c in out)


def test_split_trailing_parenthetical_alias() -> None:
    from app.rag.kg.extraction.alias import split_trailing_parenthetical_alias

    assert split_trailing_parenthetical_alias("Large Language Model (LLM)") == ("Large Language Model", "LLM")
    assert split_trailing_parenthetical_alias("清华大学（THU）") == ("清华大学", "THU")
    assert split_trailing_parenthetical_alias("Foo") is None


def test_choose_alias_direction_cjk_fullname_vs_ascii_abbrev() -> None:
    from app.rag.kg.extraction.alias import choose_alias_direction

    assert choose_alias_direction("清华大学", "THU") == ("THU", "清华大学")


def test_choose_alias_direction_cjk_fullname_vs_cjk_short() -> None:
    from app.rag.kg.extraction.alias import choose_alias_direction

    assert choose_alias_direction("清华大学", "清华") == ("清华", "清华大学")


def test_choose_alias_direction_cjk_institute_abbrev() -> None:
    from app.rag.kg.extraction.alias import choose_alias_direction

    assert choose_alias_direction("中国科学院", "中科院") == ("中科院", "中国科学院")


def test_best_suffix_match_prefers_longest() -> None:
    from app.rag.kg.extraction.alias import best_suffix_match

    assert best_suffix_match("我们使用清华大学", ["大学", "清华大学"]) == "清华大学"
