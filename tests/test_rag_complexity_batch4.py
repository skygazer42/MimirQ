from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

import app.rag.pipeline_plugins.local_runner as local_runner
from app.parsing.utils import text as text_utils
from app.rag.chunking.contextual_enrichment import build_context_prefix
from app.rag.chunking.strategies.http_trace import HTTPTraceChunker
from app.rag.chunking.strategies.sitemap_xml import SitemapXMLChunker
from app.rag.chunking.strategies.xml_feed import XMLFeedChunker
from app.rag.evaluation.kg_hardcase_generator import Hardcase, sanitize_hardcases
from app.rag.evaluation.poc_runner.query_pattern_miner import mine_query_patterns
from app.rag.pipeline_plugins.contracts import DISPLAY_METADATA_KEY, EVALUABLE_METADATA_KEY
from app.rag.policy.query_expansion import build_lightweight_subquery_queries
from app.rag.preprocessing.code_blocks import strip_fenced_code_line_numbers
from app.rag.preprocessing.cpu_tagger import extract_cpu_tags
from app.rag.preprocessing.secrets import SecretMatch, find_secret_matches
from app.rag.retrieval.hybrid.common import _iter_metadata_exact_anchor_values


def _summarize_chunks(chunker, text: str) -> list[tuple[str, dict]]:
    docs = chunker.split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    return [
        (
            doc.page_content,
            {key: value for key, value in doc.metadata.items() if key != "source"},
        )
        for doc in docs
    ]


def test_read_text_file_characterizes_bom_and_candidate_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    utf16_path = tmp_path / "utf16.txt"
    utf16_path.write_bytes("hello世界".encode("utf-16"))
    assert text_utils.read_text_file(utf16_path) == text_utils.DecodedText(
        text="hello世界",
        encoding="utf-16",
        confidence=1.0,
        had_bom=True,
    )

    class _FakeChardet:
        @staticmethod
        def detect(_blob: bytes) -> dict[str, object]:
            return {"encoding": "ascii", "confidence": 0.9}

    monkeypatch.setattr(text_utils, "_get_chardet", lambda: _FakeChardet(), raising=True)
    gb_path = tmp_path / "gb.txt"
    gb_path.write_bytes("中文内容，测试".encode("gb18030"))

    assert text_utils.read_text_file(gb_path) == text_utils.DecodedText(
        text="中文内容，测试",
        encoding="gb18030",
        confidence=0.0,
        had_bom=False,
    )


def test_build_context_prefix_characterizes_english_and_cjk_outputs() -> None:
    english = build_context_prefix(
        "Alpha beta gamma. Beta topic and evidence.",
        document_title="Guide",
        meta={"outline_path": ["Start", "Detail"]},
        max_prefix_chars=240,
        keywords_top_k=3,
        keywords_max_chars=2000,
    )
    chinese = build_context_prefix(
        "这是一个关于检索治理和数据治理的章节，检索治理需要人工复核。",
        document_title="治理手册",
        meta={"header_path": "总则 / 范围"},
        max_prefix_chars=60,
        keywords_top_k=4,
        keywords_max_chars=2000,
    )

    assert english == "Excerpt from document 'Guide'. Section: Start / Detail. Keywords: beta, alpha, gamma."
    assert chinese == "本文档《治理手册》的摘录。 章节：总则 / 范围。 关键词：治理，检索，这是，数据。"


def test_http_trace_chunker_characterizes_preamble_offsets_and_request_metadata() -> None:
    text = (
        "trace header\n"
        "GET /alpha HTTP/1.1\n"
        "> Host: ex\n"
        "< HTTP/1.1 200 OK\n"
        "body a\n"
        "POST /beta HTTP/1.1\n"
        "> Host: ex\n"
        "< HTTP/1.1 404 Not Found\n"
        "body b\n"
    )

    assert _summarize_chunks(HTTPTraceChunker(1000, 0), text) == [
        (
            "trace header",
            {
                "chunk_strategy": "http_trace",
                "start_char": 0,
                "end_char": 12,
                "http_trace_preamble": True,
                "doc_type_kwd": "http",
                "chunk_index": 0,
            },
        ),
        (
            "GET /alpha HTTP/1.1\n> Host: ex\n< HTTP/1.1 200 OK\nbody a",
            {
                "chunk_strategy": "http_trace",
                "start_char": 13,
                "end_char": 68,
                "doc_type_kwd": "http",
                "http_method": "GET",
                "http_path": "/alpha",
                "http_request_index": 0,
                "http_request_count": 2,
                "http_status": 200,
                "chunk_index": 1,
            },
        ),
        (
            "POST /beta HTTP/1.1\n> Host: ex\n< HTTP/1.1 404 Not Found\nbody b",
            {
                "chunk_strategy": "http_trace",
                "start_char": 69,
                "end_char": 131,
                "doc_type_kwd": "http",
                "http_method": "POST",
                "http_path": "/beta",
                "http_request_index": 1,
                "http_request_count": 2,
                "http_status": 404,
                "chunk_index": 2,
            },
        ),
    ]


def test_sitemap_and_xml_feed_chunkers_characterize_offsets_and_entry_metadata() -> None:
    sitemap_text = (
        '<?xml version="1.0"?>\n'
        "<urlset>\n"
        "<url><loc>https://a.example/x</loc></url>\n"
        "<url><loc>https://a.example/y</loc></url>\n"
        "</urlset>\n"
    )
    xml_feed_text = (
        '<?xml version="1.0"?>\n'
        "<rss><channel>\n"
        "<item><title>Alpha &amp; Beta</title><description>First</description></item>\n"
        "<item><title>Gamma</title><description>Second</description></item>\n"
        "</channel></rss>\n"
    )

    assert _summarize_chunks(SitemapXMLChunker(1000, 0), sitemap_text) == [
        (
            '<?xml version="1.0"?>\n<urlset>',
            {
                "chunk_strategy": "sitemap_xml",
                "start_char": 0,
                "end_char": 30,
                "sitemap_xml_preamble": True,
                "doc_type_kwd": "sitemap",
                "chunk_index": 0,
            },
        ),
        (
            "<url><loc>https://a.example/x</loc></url>",
            {
                "chunk_strategy": "sitemap_xml",
                "start_char": 31,
                "end_char": 72,
                "doc_type_kwd": "sitemap",
                "sitemap_kind": "url",
                "sitemap_index": 0,
                "sitemap_count": 2,
                "sitemap_loc": "https://a.example/x",
                "chunk_index": 1,
            },
        ),
        (
            "<url><loc>https://a.example/y</loc></url>",
            {
                "chunk_strategy": "sitemap_xml",
                "start_char": 73,
                "end_char": 114,
                "doc_type_kwd": "sitemap",
                "sitemap_kind": "url",
                "sitemap_index": 1,
                "sitemap_count": 2,
                "sitemap_loc": "https://a.example/y",
                "chunk_index": 2,
            },
        ),
    ]
    assert _summarize_chunks(XMLFeedChunker(1000, 0), xml_feed_text) == [
        (
            '<?xml version="1.0"?>\n<rss><channel>',
            {
                "chunk_strategy": "xml_feed",
                "start_char": 0,
                "end_char": 36,
                "xml_feed_preamble": True,
                "doc_type_kwd": "xml",
                "chunk_index": 0,
            },
        ),
        (
            "<item><title>Alpha &amp; Beta</title><description>First</description></item>",
            {
                "chunk_strategy": "xml_feed",
                "start_char": 37,
                "end_char": 113,
                "doc_type_kwd": "xml",
                "xml_feed_kind": "item",
                "xml_feed_index": 0,
                "xml_feed_count": 2,
                "xml_feed_title": "Alpha & Beta",
                "chunk_index": 1,
            },
        ),
        (
            "<item><title>Gamma</title><description>Second</description></item>",
            {
                "chunk_strategy": "xml_feed",
                "start_char": 114,
                "end_char": 180,
                "doc_type_kwd": "xml",
                "xml_feed_kind": "item",
                "xml_feed_index": 1,
                "xml_feed_count": 2,
                "xml_feed_title": "Gamma",
                "chunk_index": 2,
            },
        ),
    ]


def test_sanitize_hardcases_characterizes_parse_fallback_dedupe_and_truncation() -> None:
    assert sanitize_hardcases({"raw": "parse failed"}, max_items=3, max_chars=50) == []
    assert sanitize_hardcases(
        {
            "hardcases": [
                {"kind": "knowledge_pressure", "question": "  Alpha   beta  ", "rationale": "  why  "},
                {"kind": "reasoning_pressure", "question": "Alpha beta"},
                {"kind": "knowledge_pressure", "question": "x" * 500},
            ]
        },
        max_items=3,
        max_chars=20,
    ) == [
        Hardcase(kind="knowledge_pressure", question="Alpha beta", rationale="why"),
        Hardcase(kind="knowledge_pressure", question="x" * 20, rationale=None),
    ]


def test_mine_query_patterns_characterizes_abbreviations_multi_intent_and_keyword_ranking() -> None:
    rows = [
        {
            "interaction_id": "1",
            "original_query": "什么是RAG？另外报销 policy？",
            "final_context_filenames": ["a.txt", "b.txt"],
        },
        {
            "interaction_id": "2",
            "original_query": "RAG FAQ FAQ",
            "final_context_filenames": ["a.txt"],
        },
        {
            "interaction_id": "3",
            "original_query": "报销 policy 2024 2024",
            "final_context_filenames": ["c.txt", "a.txt"],
        },
    ]

    assert mine_query_patterns(rows, abbreviation_min_frequency=1, top_k_keywords=5) == {
        "abbreviations": [
            {"token": "RAG", "count": 2},
            {"token": "FAQ", "count": 2},
            {"token": "2024", "count": 2},
            {"token": "什么是", "count": 1},
            {"token": "另外报销", "count": 1},
            {"token": "报销", "count": 1},
        ],
        "glossary_candidates": [
            {"token": "RAG", "count": 2, "source": "abbreviation_frequency"},
            {"token": "FAQ", "count": 2, "source": "abbreviation_frequency"},
            {"token": "2024", "count": 2, "source": "abbreviation_frequency"},
            {"token": "什么是", "count": 1, "source": "abbreviation_frequency"},
            {"token": "另外报销", "count": 1, "source": "abbreviation_frequency"},
            {"token": "报销", "count": 1, "source": "abbreviation_frequency"},
        ],
        "multi_intent_queries": [
            {
                "interaction_id": "1",
                "query": "什么是RAG？另外报销 policy？",
                "signals": ["multiple_question_marks", "multi_intent_connector"],
            }
        ],
        "document_heat": [
            {"filename": "a.txt", "count": 3},
            {"filename": "b.txt", "count": 1},
            {"filename": "c.txt", "count": 1},
        ],
        "keyword_scores": [
            {"token": "FAQ", "score": 4.7726, "count": 2},
            {"token": "2024", "score": 4.7726, "count": 2},
            {"token": "policy", "score": 3.3863, "count": 2},
            {"token": "RAG", "score": 3.3863, "count": 2},
            {"token": "报销", "score": 2.3863, "count": 1},
        ],
    }


def test_run_plugin_stages_characterizes_success_and_invocation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = SimpleNamespace(
        id="demo",
        version="1",
        entries={"chunk": object(), "kg": object()},
        refs={"chunk": "plugin:chunk", "kg": "plugin:kg"},
        metadata_schema={"schema": "x"},
        retrieval_text_schema={"schema": "r"},
    )

    monkeypatch.setattr(local_runner, "load_descriptor_stage_callable", lambda descriptor, stage: stage, raising=True)
    monkeypatch.setattr(local_runner, "strip_reserved_platform_metadata_views", lambda docs: list(docs), raising=True)
    monkeypatch.setattr(
        local_runner,
        "_invoke_plugin",
        lambda func, documents, params, context: (
            [Document(page_content=f"{func}:{documents[0].page_content}", metadata={"stage": func})]
            if func == "chunk"
            else [SimpleNamespace(content="event")]
        ),
        raising=True,
    )
    monkeypatch.setattr(local_runner, "_coerce_documents", lambda result, stage, plugin_ref: list(result), raising=True)
    monkeypatch.setattr(
        local_runner, "validate_no_reserved_platform_metadata_views", lambda metadata, field_label: None, raising=True
    )
    monkeypatch.setattr(
        local_runner,
        "validate_documents_metadata",
        lambda output_documents, metadata_schema, stage: {"ok": True, "checked": len(output_documents), "errors": []},
        raising=True,
    )
    monkeypatch.setattr(
        local_runner,
        "apply_metadata_schema_views",
        lambda output_documents, metadata_schema, stage: [
            Document(page_content=doc.page_content, metadata={**doc.metadata, "applied_stage": stage})
            for doc in output_documents
        ],
        raising=True,
    )
    monkeypatch.setattr(
        local_runner,
        "apply_retrieval_text_schema",
        lambda output_documents, retrieval_text_schema, stage: [
            Document(page_content=f"{doc.page_content}|retrieval", metadata=doc.metadata) for doc in output_documents
        ],
        raising=True,
    )
    monkeypatch.setattr(
        local_runner, "_coerce_kg_events", lambda result, documents, plugin_ref: list(result), raising=True
    )
    monkeypatch.setattr(
        local_runner,
        "validate_kg_events_metadata",
        lambda events, metadata_schema: {"ok": True, "checked": len(events), "errors": []},
        raising=True,
    )

    docs, reports, passed = local_runner._run_plugin_stages(
        descriptor=descriptor,
        input_documents=[Document(page_content="body", metadata={"source": "x"})],
        stages=["chunk", "kg"],
    )

    assert docs == [
        Document(page_content="chunk:body|retrieval", metadata={"stage": "chunk", "applied_stage": "chunk"})
    ]
    assert reports == {
        "chunk": {
            "passed": True,
            "input_count": 1,
            "output_count": 1,
            "output_chars": 20,
            "metadata_validation": {"ok": True, "checked": 1, "errors": []},
        },
        "kg": {
            "passed": True,
            "input_count": 1,
            "output_count": 1,
            "output_chars": 5,
            "kg_validation": {"ok": True, "checked": 1, "errors": []},
        },
    }
    assert passed is True

    monkeypatch.setattr(
        local_runner,
        "_invoke_plugin",
        lambda func, documents, params, context: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=True,
    )

    docs, reports, passed = local_runner._run_plugin_stages(
        descriptor=descriptor,
        input_documents=[Document(page_content="body", metadata={})],
        stages=["chunk"],
    )

    assert docs == []
    assert reports == {
        "chunk": {
            "passed": False,
            "input_count": 1,
            "output_count": 0,
            "output_chars": 0,
            "metadata_validation": {"ok": False, "checked": 0, "errors": [{"reason": "boom"}]},
        }
    }
    assert passed is False


def test_build_lightweight_subquery_queries_characterizes_sentence_and_enum_splitting() -> None:
    assert build_lightweight_subquery_queries(
        "我想了解报销政策，同时看一下请假流程，以及差旅、住宿标准该怎么处理",
        max_queries=5,
        min_query_chars=10,
        min_part_chars=2,
        max_part_chars=20,
    ) == ["了解报销政策", "看一下请假流程", "差旅、住宿标准", "差旅", "住宿标准"]


def test_strip_fenced_code_line_numbers_characterizes_number_stripping_and_fence_preservation() -> None:
    result = strip_fenced_code_line_numbers(
        "before\n```python\n1  alpha\n2  beta\n3  gamma\n4  delta\n5  epsilon\n```\nafter"
    )

    assert result.text == "before\n```python\n alpha\n beta\n gamma\n delta\n epsilon\n```\nafter"
    assert result.blocks_changed == 1
    assert result.lines_stripped == 5
    assert result.changed is True


def test_extract_cpu_tags_characterizes_sensitivity_topics_and_quality_spans() -> None:
    result = extract_cpu_tags(
        text="知识库检索方案。联系人 alice@example.com。建议完善脱敏流程，存在风险，需要人工复核。知识库检索需要优化。",
        keyword_top_k=5,
        max_items=20,
    ).model_dump()

    assert result == {
        "summary": None,
        "document_tags": [
            {"type": "domain", "value": "企业知识库", "label": "领域", "confidence": 0.78, "source": "cpu"},
            {"type": "industry", "value": "通用企业服务", "label": "行业", "confidence": 0.66, "source": "cpu"},
            {"type": "category", "value": "检索治理", "label": "分类", "confidence": 0.7, "source": "cpu"},
            {"type": "category", "value": "质量评估", "label": "分类", "confidence": 0.68, "source": "cpu"},
            {"type": "doc_type", "value": "治理方案", "label": "文档类型", "confidence": 0.78, "source": "cpu"},
            {"type": "sensitivity", "value": "restricted", "label": "敏感度", "confidence": 0.92, "source": "cpu"},
            {
                "type": "quality",
                "value": "含敏感信息，建议人工复核",
                "label": "质量线索",
                "confidence": 0.9,
                "source": "cpu",
            },
            {"type": "topic", "value": "知识库检索", "label": "主题", "confidence": 0.78, "source": "cpu"},
            {"type": "topic", "value": "知识库检索方案", "label": "主题", "confidence": 0.68, "source": "cpu"},
            {"type": "quality", "value": "需要人工复核", "label": "质量线索", "confidence": 0.74, "source": "cpu"},
            {
                "type": "quality",
                "value": "建议完善脱敏流程，存在风险，需要人工复核",
                "label": "质量线索",
                "confidence": 0.74,
                "source": "cpu",
            },
        ],
        "span_annotations": [
            {"text": "知识库检索", "type": "keyword", "label": "主题关键词", "confidence": 0.78, "source": "cpu"},
            {"text": "知识库检索方案", "type": "keyword", "label": "主题关键词", "confidence": 0.68, "source": "cpu"},
            {"text": "需要人工复核", "type": "custom", "label": "动作项", "confidence": 0.82, "source": "cpu"},
            {
                "text": "建议完善脱敏流程，存在风险，需要人工复核",
                "type": "custom",
                "label": "风险线索",
                "confidence": 0.8,
                "source": "cpu",
            },
        ],
        "provider": "cpu",
    }


def test_find_secret_matches_characterizes_overlap_avoidance_and_result_order() -> None:
    text = (
        "Bearer ABCDEFGHIJKL12345 and sk-abcdefghijklmnop and "
        "-----BEGIN PRIVATE KEY-----\nXYZ\n-----END PRIVATE KEY-----"
    )

    assert find_secret_matches(text, max_matches=10) == [
        SecretMatch(kind="bearer_token", start=0, end=24, text="Bearer ABCDEFGHIJKL12345"),
        SecretMatch(kind="openai_key", start=29, end=48, text="sk-abcdefghijklmnop"),
        SecretMatch(
            kind="private_key",
            start=53,
            end=110,
            text="-----BEGIN PRIVATE KEY-----\nXYZ\n-----END PRIVATE KEY-----",
        ),
    ]


def test_iter_metadata_exact_anchor_values_characterizes_view_priority_and_deduping() -> None:
    meta = {
        "question": "Alpha Desk materials",
        "_ignored": "x",
        "aliases": ["Alpha Desk", "materials"],
        DISPLAY_METADATA_KEY: {"question": "Alpha Desk materials", "alias": "Alpha Desk"},
        EVALUABLE_METADATA_KEY: {"alias": "Alpha Desk", "code": ["X1", "X1"]},
    }

    assert _iter_metadata_exact_anchor_values(meta) == [
        ("alias", "Alpha Desk"),
        ("code", "X1"),
        ("question", "Alpha Desk materials"),
        ("aliases", "Alpha Desk"),
        ("aliases", "materials"),
    ]
