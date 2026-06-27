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


def test_processor_llm_auto_tagging_writes_document_level_metadata(monkeypatch):  # noqa: ANN001
    from langchain_core.documents import Document

    from app.parsing.processors.processor import DocumentProcessorService
    from app.rag.preprocessing.llm_tagger import LLMDocumentTag, LLMTaggingResult
    from app.services.pipeline_config import resolve_pipeline_options
    from app.types.pipeline import PipelineOptions

    async def _fake_extract_llm_tags(**_kwargs):  # noqa: ANN202
        return LLMTaggingResult(
            summary="自动识别出的入库主题。",
            document_tags=[
                LLMDocumentTag(type="topic", value="入库质量"),
                LLMDocumentTag(type="keyword", value="PII"),
            ],
            provider="fake",
        )

    import app.rag.preprocessing.llm_tagger as tagger_mod

    monkeypatch.setattr(tagger_mod, "extract_llm_tags", _fake_extract_llm_tags, raising=True)
    items = [Document(page_content="入库前需要检查 PII 和质量画像。", metadata={})]
    effective = resolve_pipeline_options(
        PipelineOptions(
            governance_llm_auto_tagging_enabled=True,
            governance_llm_auto_tagging_max_chars=500,
            governance_llm_auto_tagging_max_items=8,
        )
    )

    meta = asyncio.run(DocumentProcessorService()._apply_llm_auto_tagging(items, pipeline_effective=effective))

    assert meta == {"enabled": True, "used": True, "provider": "fake", "tag_count": 1, "keyword_count": 1}
    assert items[0].metadata["document_tags"] == ["入库质量"]
    assert items[0].metadata["document_keywords"] == ["PII"]
    assert items[0].metadata["document_llm_auto_summary"] == "自动识别出的入库主题。"

    DocumentProcessorService._strip_doc_enrichment_fields(items)

    assert "document_tags" not in items[0].metadata
    assert "document_keywords" not in items[0].metadata
    assert "document_llm_auto_tags" not in items[0].metadata
    assert "document_llm_auto_summary" not in items[0].metadata
