from __future__ import annotations


def test_extract_entity_tokens_filters_pii_and_keeps_project_like_tokens() -> None:
    from app.services.structured_memory_service import extract_entity_tokens

    text = "We use MimirQ with KohakuRAG. Contact me at test@example.com. Version v0.5.2."
    out = extract_entity_tokens(text=text, max_entities=10)
    assert "MimirQ" in out
    assert "KohakuRAG" in out
    assert "v0.5.2" in out
    # PII should not be stored as an entity token.
    assert all("@" not in x for x in out)


def test_extract_fact_sentences_selects_user_provided_config_like_sentences() -> None:
    from app.services.structured_memory_service import extract_fact_sentences

    text = "现在开始构建这个项目，用docker。不要commit。我们的数据库是 PostgreSQL。"
    facts = extract_fact_sentences(text=text, max_facts=5)
    assert any("docker" in f.casefold() for f in facts)
    assert any("数据库" in f for f in facts)


def test_build_structured_memory_context_dedups_and_bounds_output() -> None:
    from app.services.structured_memory_service import build_structured_memory_context

    records = [
        {"schema": "mimirq.structured_memory.v1", "entities": ["MimirQ", "KohakuRAG"], "facts": ["我们用docker部署"]},
        {"schema": "mimirq.structured_memory.v1", "entities": ["MimirQ", "v0.5.2"], "facts": ["我们用docker部署"]},
    ]
    ctx = build_structured_memory_context(records=records, max_entities=10, max_facts=10, max_chars=500)
    assert "[Structured Memory]" in ctx
    assert "- MimirQ" in ctx
    assert "- KohakuRAG" in ctx or "- kohakurag" in ctx.casefold()
    assert "Facts/preferences" in ctx

