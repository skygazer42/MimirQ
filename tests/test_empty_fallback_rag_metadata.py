import asyncio

import pytest
from pydantic import ValidationError

from app.rag.ingestion.governance.tagging.llm_tagger import extract_llm_tags
from app.rag.ingestion.governance.tagging.metadata_enrichment import build_document_metadata_enrichment


def test_metadata_enrichment_uses_valid_text_and_keeps_existing_keywords():
    result = build_document_metadata_enrichment(
        "Document body",
        metadata={
            "document_title": "0",
            "document_summary": "False",
            "document_keywords": ["existing"],
        },
        generate_questions=False,
    )
    assert result["document_title"] == "0"
    assert result["document_summary"] == "False"
    assert result["document_keywords"] == ["existing"]

    missing_text = build_document_metadata_enrichment(
        "Document body", metadata={"document_title": 0, "document_summary": False}, generate_questions=False
    )
    assert "document_title" not in missing_text
    assert missing_text["document_summary"] == "Document body"


class _Tagger:
    def __init__(self, response):
        self.response = response

    async def chat_with_schema(self, *args, **kwargs):
        return self.response


def test_llm_tags_preserve_numeric_looking_text():
    result = asyncio.run(extract_llm_tags(text="Document body", llm_client=_Tagger({"topics": ["0", "False"]})))
    assert [tag.value for tag in result.document_tags] == ["0", "False"]


def test_llm_tags_reject_topic_objects_outside_the_response_schema():
    with pytest.raises(ValidationError, match=r"topics\.0"):
        asyncio.run(
            extract_llm_tags(text="Document body", llm_client=_Tagger({"topics": [{"label": "example"}]}))
        )


def test_llm_annotations_preserve_text_and_default_optional_labels():
    result = asyncio.run(
        extract_llm_tags(
            text="Document 0 False",
            llm_client=_Tagger(
                {
                    "annotations": [
                        {"text": "No matching source text"},
                        {"text": "Document"},
                        {"text": "0"},
                        {"text": "0"},
                        {"text": "False"},
                    ]
                }
            ),
        )
    )
    assert [span.text for span in result.span_annotations] == ["No matching source text", "Document", "0", "False"]
    assert all(span.type == "custom" for span in result.span_annotations)
