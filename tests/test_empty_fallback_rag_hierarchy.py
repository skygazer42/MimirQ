import pytest
from langchain_core.documents import Document

from app.rag.ingestion.chunking.strategies.markup import markdown_hierarchy
from app.rag.ingestion.chunking.strategies.text import text_hierarchy


@pytest.mark.parametrize("module", [markdown_hierarchy, text_hierarchy])
@pytest.mark.parametrize(
    "payload,key",
    [
        ({"paragraphs": [{"id": "paragraph-1"}], "sentences": []}, "text"),
        ({"paragraphs": [], "sentences": [{"text": "Sentence."}]}, "parent_id"),
        (None, "id"),
    ],
)
def test_hierarchy_chunking_exposes_missing_internal_record_fields(monkeypatch, module, payload, key):
    if payload is None:
        result = module.hierarchical_chunk_markdown("Paragraph.")
        paragraph = dict(result["paragraphs"][0])
        del paragraph[key]
        payload = {"paragraphs": [paragraph], "sentences": []}
    monkeypatch.setattr(module, "hierarchical_chunk_markdown", lambda text: payload)
    chunker_type = (
        markdown_hierarchy.MarkdownHierarchyChunker
        if module is markdown_hierarchy
        else text_hierarchy.TextHierarchyChunker
    )
    chunker = chunker_type(chunk_size=400, chunk_overlap=0)
    with pytest.raises(KeyError, match=key):
        chunker.split_documents([Document(page_content="Document text.")])
