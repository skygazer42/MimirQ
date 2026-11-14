import asyncio

from app.rag.preprocessing.llm_tagger import extract_llm_tags
from app.rag.preprocessing.metadata_enrichment import build_document_metadata_enrichment


def test_metadata_enrichment_preserves_supplied_falsy_scalars():
    result = build_document_metadata_enrichment(
        "Document body",
        metadata={
            "document_title": 0,
            "document_summary": False,
            "document_keywords": ["existing"],
        },
        generate_questions=False,
    )
    assert result["document_title"] == "0"
    assert result["document_summary"] == "False"


class _Tagger:
    def __init__(self, response):
        self.response = response

    async def chat_with_schema(self, *args, **kwargs):
        return self.response


def test_llm_tags_preserve_falsy_scalar_values():
    result = asyncio.run(
        extract_llm_tags(text="Document body", llm_client=_Tagger({"topics": [0, False]}))
    )
    assert [tag.value for tag in result.document_tags] == ["0", "False"]


def test_llm_tag_object_omitted_aliases_remain_optional():
    result = asyncio.run(
        extract_llm_tags(
            text="Document body",
            llm_client=_Tagger({"topics": [{"label": 0}, {"name": None, "label": False}]}),
        )
    )
    assert [tag.value for tag in result.document_tags] == ["0", "False"]


def test_llm_annotation_no_matches_preserve_valid_siblings_and_scalar_text():
    result = asyncio.run(
        extract_llm_tags(
            text="Document 0 False",
            llm_client=_Tagger(
                {"annotations": [{"type": "keyword"}, {"text": None}, {"text": "Document"}, {"text": 0}, {"text": False}]}
            ),
        )
    )
    assert [span.text for span in result.span_annotations] == ["Document", "0", "False"]
