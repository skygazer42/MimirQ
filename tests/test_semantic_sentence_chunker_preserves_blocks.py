from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.semantic import SemanticSentenceChunker


def test_semantic_sentence_chunker_keeps_list_item_and_continuation_together() -> None:
    text = (
        "- ITEM1_START "
        + ("a" * 120)
        + "\n  ITEM1_CONT "
        + ("b" * 120)
        + "\n\n"
        "- ITEM2_START "
        + ("c" * 120)
        + "\n  ITEM2_CONT "
        + ("d" * 120)
        + "\n"
    )

    chunker = SemanticSentenceChunker(chunk_size=200, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])
    assert chunks

    contents = [c.page_content for c in chunks]
    assert any("ITEM1_START" in c for c in contents)
    assert any("ITEM2_START" in c for c in contents)

    for c in contents:
        assert ("ITEM1_START" in c) == ("ITEM1_CONT" in c)
        assert ("ITEM2_START" in c) == ("ITEM2_CONT" in c)


def test_semantic_sentence_chunker_keeps_fenced_code_block_together() -> None:
    code = "print('hello')\n" * 50
    text = (
        "Intro.\n\n"
        "```python\n"
        + code
        + "```\n\n"
        "Outro.\n"
    )

    chunker = SemanticSentenceChunker(chunk_size=120, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])
    assert chunks

    # The chunk containing the fenced start marker should also contain the closing fence.
    for c in chunks:
        if "```python" in c.page_content:
            assert "```\n" in c.page_content or c.page_content.rstrip().endswith("```")

