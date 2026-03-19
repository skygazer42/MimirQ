from __future__ import annotations

from app.rag.chunking.contextual_enrichment import build_context_prefix


def test_build_context_prefix_returns_none_on_empty_content() -> None:
    assert build_context_prefix("", document_title="Doc", meta={}) is None
    assert build_context_prefix("   ", document_title="Doc", meta={}) is None


def test_build_context_prefix_english_includes_title_section_and_keywords() -> None:
    prefix = build_context_prefix(
        "alpha beta beta gamma",
        document_title="My Doc",
        meta={"header_path": "Intro"},
        max_prefix_chars=400,
        keywords_top_k=3,
        keywords_max_chars=2000,
    )
    assert prefix
    assert "Excerpt from document 'My Doc'." in prefix
    assert "Section: Intro." in prefix
    assert "Keywords:" in prefix
    assert "beta" in prefix


def test_build_context_prefix_cjk_variant() -> None:
    prefix = build_context_prefix(
        "量子纠缠是一种有趣的物理现象。",
        document_title="量子论",
        meta={"outline_path": ["第一章", "基本概念"]},
        max_prefix_chars=400,
        keywords_top_k=6,
        keywords_max_chars=2000,
    )
    assert prefix
    assert "本文档《量子论》" in prefix
    assert "章节：" in prefix


def test_build_context_prefix_respects_max_prefix_chars() -> None:
    prefix = build_context_prefix(
        "alpha beta gamma delta",
        document_title="T" * 200,
        meta={"header_path": "S" * 200},
        max_prefix_chars=50,
        keywords_top_k=6,
        keywords_max_chars=2000,
    )
    assert prefix
    assert len(prefix) <= 50
    assert prefix.endswith((".", "。", "!", "！"))

