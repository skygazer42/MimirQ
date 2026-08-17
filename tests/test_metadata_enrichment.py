
from types import SimpleNamespace

import pytest

from app.rag.preprocessing import metadata_enrichment


def test_metadata_fields_take_precedence_and_keep_output_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        metadata_enrichment,
        "extract_markdown_frontmatter",
        lambda raw, strip: SimpleNamespace(stripped_text=raw, data={"title": "Frontmatter"}),
    )
    monkeypatch.setattr(
        metadata_enrichment,
        "detect_language",
        lambda *_args, **_kwargs: pytest.fail("existing language should win"),
    )
    monkeypatch.setattr(
        metadata_enrichment,
        "extract_keywords",
        lambda *_args, **_kwargs: pytest.fail("existing keywords should win"),
    )

    result = metadata_enrichment.build_document_metadata_enrichment(
        "# Body title\n\nBody text",
        metadata={
            "document_title": " Metadata title ",
            "document_tags": ["One", "one", "Two"],
            "document_summary": " Existing summary ",
            "document_keywords": ["Alpha", "alpha", "Beta"],
            "document_keywords_provider": "manual",
            "document_questions": ["Question?", "question?"],
            "document_language": "en",
            "document_language_confidence": 0.87654,
        },
    )

    assert list(result) == [
        "metadata_enrichment_schema",
        "document_title",
        "document_tags",
        "document_summary",
        "document_keywords",
        "document_keywords_provider",
        "document_questions",
        "document_language",
        "document_language_confidence",
        "document_frontmatter",
    ]
    assert result == {
        "metadata_enrichment_schema": "mimirq.metadata_enrichment.v1",
        "document_title": "Metadata title",
        "document_tags": ["One", "Two"],
        "document_summary": "Existing summary",
        "document_keywords": ["Alpha", "Beta"],
        "document_keywords_provider": "manual",
        "document_questions": ["Question?"],
        "document_language": "en",
        "document_language_confidence": 0.877,
        "document_frontmatter": {"title": "Frontmatter"},
    }


def test_frontmatter_detection_keywords_and_chinese_questions_preserve_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        metadata_enrichment,
        "extract_markdown_frontmatter",
        lambda _raw, strip: SimpleNamespace(
            stripped_text="# 文档标题\n\n第一段摘要。\n\n第二段。",
            data={"title": "前言标题", "tags": ["指南", "指南", "配置"]},
        ),
    )
    monkeypatch.setattr(
        metadata_enrichment,
        "detect_language",
        lambda text, min_chars: SimpleNamespace(language="zh", confidence=0.93456),
    )
    calls: list[tuple[str, str, int]] = []

    def keywords(text: str, *, provider: str, top_k: int):
        calls.append((text, provider, top_k))
        return ["检索", "配置", "检索"]

    monkeypatch.setattr(metadata_enrichment, "extract_keywords", keywords)

    result = metadata_enrichment.build_document_metadata_enrichment(
        "ignored raw",
        keywords_provider="jieba",
        keyword_top_k=4,
        keyword_max_chars=12,
        question_count=3,
    )

    assert result["document_title"] == "前言标题"
    assert result["document_tags"] == ["指南", "配置"]
    assert result["document_summary"] == "# 文档标题"
    assert result["document_language"] == "zh"
    assert result["document_language_confidence"] == 0.935
    assert result["document_keywords"] == ["检索", "配置"]
    assert result["document_keywords_provider"] == "jieba"
    assert result["document_questions"] == [
        "前言标题 主要讲什么？",
        "如何配置或使用 配置？",
        "前言标题 提供了哪些关键步骤或注意事项？",
    ]
    assert calls == [("# 文档标题\n\n第一段摘", "jieba", 4)]


def test_detection_failures_remain_best_effort_and_question_generation_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        metadata_enrichment,
        "extract_markdown_frontmatter",
        lambda raw, strip: SimpleNamespace(stripped_text=raw, data={}),
    )
    monkeypatch.setattr(metadata_enrichment, "extract_markdown_title", lambda _text: "Title")
    monkeypatch.setattr(
        metadata_enrichment,
        "detect_language",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("language failed")),
    )
    monkeypatch.setattr(
        metadata_enrichment,
        "extract_keywords",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("keywords failed")),
    )

    result = metadata_enrichment.build_document_metadata_enrichment(
        "# Title\n\nBody paragraph",
        generate_questions=False,
    )

    assert result == {
        "metadata_enrichment_schema": "mimirq.metadata_enrichment.v1",
        "document_title": "Title",
        "document_summary": "Body paragraph",
    }


def test_empty_text_returns_no_schema_or_enrichment() -> None:
    assert metadata_enrichment.build_document_metadata_enrichment(" \n ") == {}
