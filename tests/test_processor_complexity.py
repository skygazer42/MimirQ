from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.rag.ingestion.governance.tagging import DocumentTag, TaggingResult
from app.rag.ingestion.indexing.processor import _apply_llm_auto_tagging
from app.rag.ingestion.pipeline import _filter_short_chunks


@pytest.mark.asyncio
async def test_apply_llm_auto_tagging_merges_tags_keywords_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.ingestion.governance.tagging import llm_tagger

    items = [
        Document(
            page_content="Alpha body",
            metadata={
                "document_tags": ["existing-tag"],
                "document_keywords": ["existing-keyword"],
            },
        ),
        Document(page_content="Beta body", metadata={}),
    ]

    async def _extract_llm_tags(**_kwargs: Any) -> TaggingResult:
        return TaggingResult(
            summary="summary text",
            provider="llm",
            document_tags=[
                DocumentTag(type="topic", value="new-tag", label="", confidence=0.85, source="llm"),
                DocumentTag(type="keyword", value="new-keyword", label="", confidence=0.85, source="llm"),
                DocumentTag(type="topic", value="existing-tag", label="", confidence=0.85, source="llm"),
            ],
        )

    monkeypatch.setattr(llm_tagger, "extract_llm_tags", _extract_llm_tags, raising=True)

    result = await _apply_llm_auto_tagging(
        items,
        pipeline_effective=SimpleNamespace(
            governance_llm_auto_tagging_enabled=True,
            governance_llm_auto_tagging_max_chars=3000,
            governance_llm_auto_tagging_max_items=4,
        ),
    )

    assert result == {
        "enabled": True,
        "used": True,
        "provider": "llm",
        "tag_count": 2,
        "keyword_count": 2,
    }
    assert items[0].metadata["document_tags"] == ["existing-tag", "new-tag"]
    assert items[0].metadata["document_keywords"] == ["existing-keyword", "new-keyword"]
    assert items[0].metadata["document_keywords_provider"] == "llm"
    assert items[0].metadata["document_llm_auto_summary"] == "summary text"
    assert items[0].metadata["document_llm_auto_tags"] == [
        {
            "type": "topic",
            "value": "new-tag",
            "label": "",
            "confidence": 0.85,
            "source": "llm",
        },
        {
            "type": "keyword",
            "value": "new-keyword",
            "label": "",
            "confidence": 0.85,
            "source": "llm",
        },
        {
            "type": "topic",
            "value": "existing-tag",
            "label": "",
            "confidence": 0.85,
            "source": "llm",
        },
    ]


@pytest.mark.asyncio
async def test_apply_llm_auto_tagging_reports_empty_text_without_mutation() -> None:
    items = [Document(page_content="   ", metadata={"document_tags": ["keep-me"]})]

    result = await _apply_llm_auto_tagging(
        items,
        pipeline_effective=SimpleNamespace(
            governance_llm_auto_tagging_enabled=True,
            governance_llm_auto_tagging_max_chars=3000,
            governance_llm_auto_tagging_max_items=16,
        ),
    )

    assert result == {"enabled": True, "used": False, "reason": "empty_text"}
    assert items[0].metadata == {"document_tags": ["keep-me"]}


def test_filter_short_chunks_keeps_asset_chunks_below_threshold() -> None:
    chunks = [
        Document(page_content="short", metadata={"doc_type_kwd": "image", "img_id": "img-1"}),
        Document(page_content="tiny", metadata={}),
    ]

    filtered = _filter_short_chunks(chunks, min_chars=20, document_id=uuid4())

    assert filtered == [chunks[0]]


def test_filter_short_chunks_keeps_longest_chunk_when_all_are_short() -> None:
    chunks = [
        Document(page_content="a", metadata={}),
        Document(page_content="abcd", metadata={}),
        Document(page_content="ab", metadata={}),
    ]

    filtered = _filter_short_chunks(chunks, min_chars=20, document_id=uuid4())

    assert filtered == [chunks[1]]
