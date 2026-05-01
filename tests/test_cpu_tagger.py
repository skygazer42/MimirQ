from __future__ import annotations


def test_cpu_tagger_returns_semantic_tags_without_llm() -> None:
    from app.rag.preprocessing.cpu_tagger import extract_cpu_tags

    text = (
        "MimirQ 文档治理方案：核心能力包括知识库检索、数据治理和入库质量分析，"
        "建议后续重点完善入库流程。联系人 zhangsan@example.com。"
    )
    result = extract_cpu_tags(text=text, keyword_provider="simple", keyword_top_k=8, max_items=20)

    tags = {(tag.type, tag.value, tag.source) for tag in result.document_tags}
    assert ("topic", "知识库检索", "cpu") in tags
    assert ("topic", "数据治理", "cpu") in tags
    assert ("category", "入库流程", "cpu") in tags
    assert ("domain", "企业知识库", "cpu") in tags
    assert ("doc_type", "治理方案", "cpu") in tags
    assert ("sensitivity", "restricted", "cpu") in tags
    assert ("quality", "含敏感信息，建议人工复核", "cpu") in tags

    spans = {(item.text, item.type, item.label, item.source) for item in result.span_annotations}
    assert ("知识库检索", "keyword", "主题关键词", "cpu") in spans
    assert ("完善入库流程", "custom", "动作项", "cpu") in spans
    assert not any(item.text == "zhangsan@example.com" and item.type == "keyword" for item in result.span_annotations)
