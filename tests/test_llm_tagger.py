from __future__ import annotations

import asyncio


class _FakeLLM:
    async def chat_with_schema(self, *_args, **_kwargs):  # noqa: ANN202
        return {
            "summary": "围绕知识库入库质量与检索治理的优化建议。",
            "topics": ["知识库检索", "数据治理"],
            "categories": ["入库流程"],
            "domain": "企业知识库",
            "industry": "通用企业服务",
            "doc_type": "治理方案",
            "sensitivity": "internal",
            "keywords_semantic": ["入库质量分析"],
            "quality_signals": ["需要人工复核"],
            "annotations": [
                {"text": "完善入库流程", "type": "custom", "label": "动作项", "confidence": 0.91}
            ],
        }


def test_llm_tagger_normalizes_document_tags_and_span_annotations():  # noqa: ANN001
    from app.rag.preprocessing.llm_tagger import extract_llm_tags

    result = asyncio.run(
        extract_llm_tags(
            text="核心能力包括知识库检索、数据治理和入库质量分析，建议后续重点完善入库流程。",
            llm_client=_FakeLLM(),
        )
    )

    assert result.summary == "围绕知识库入库质量与检索治理的优化建议。"
    tags = {(tag.type, tag.value) for tag in result.document_tags}
    assert ("topic", "知识库检索") in tags
    assert ("topic", "数据治理") in tags
    assert ("category", "入库流程") in tags
    assert ("domain", "企业知识库") in tags
    assert ("industry", "通用企业服务") in tags
    assert ("doc_type", "治理方案") in tags
    assert ("sensitivity", "internal") in tags
    assert ("quality", "需要人工复核") in tags

    assert len(result.span_annotations) == 1
    span = result.span_annotations[0]
    assert span.text == "完善入库流程"
    assert span.label == "动作项"
    assert span.source == "llm"


def test_llm_tagger_context_uses_head_and_tail_for_long_documents():  # noqa: ANN001
    from app.rag.preprocessing.llm_tagger import build_tagger_context

    text = "A" * 120 + "MIDDLE" + "Z" * 120
    context = build_tagger_context(text, max_chars=80)

    assert context.startswith("A" * 40)
    assert "[... omitted middle content ...]" in context
    assert context.endswith("Z" * 40)
    assert "MIDDLE" not in context
