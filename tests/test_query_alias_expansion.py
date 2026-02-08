from __future__ import annotations


def test_coerce_query_aliases_normalizes_and_dedups() -> None:
    from app.rag.query_expansion import coerce_query_aliases

    raw = {
        "LLM": ["large language model", "large language model", "   "],
        "foo": "bar",
        "": ["x"],
        None: ["y"],
    }
    out = coerce_query_aliases(raw)
    assert out["LLM"] == ["large language model"]
    assert out["foo"] == ["bar"]
    assert "" not in out


def test_generate_alias_queries_is_symmetric_and_case_insensitive_for_ascii() -> None:
    from app.rag.query_expansion import generate_alias_queries

    aliases = {"sso": ["single sign-on"]}

    variants, meta = generate_alias_queries(query="Use SSO for auth", aliases=aliases, max_queries=5)
    assert meta["enabled"] is True
    assert "Use single sign-on for auth" in variants

    variants2, _meta2 = generate_alias_queries(query="Enable single sign-on", aliases=aliases, max_queries=5)
    assert "Enable sso" in variants2


def test_generate_alias_queries_respects_max_queries() -> None:
    from app.rag.query_expansion import generate_alias_queries

    aliases = {"a": ["b", "c", "d", "e"]}
    variants, meta = generate_alias_queries(query="a", aliases=aliases, max_queries=1)
    assert meta["generated"] == 1
    assert len(variants) == 1

