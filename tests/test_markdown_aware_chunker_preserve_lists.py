from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.markdown import MarkdownAwareChunker


def test_markdown_aware_preserve_lists_keeps_item_continuation_together() -> None:
    # Without list preservation, RecursiveCharacterTextSplitter can split a list item between the
    # bullet line and its indented continuation line(s), losing per-item coherence.
    text = (
        "# Title\n\n"
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

    chunker = MarkdownAwareChunker(
        chunk_size=200,
        chunk_overlap=0,
        preserve_code_blocks=False,
        preserve_lists=True,
        max_header_depth=1,
    )
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])
    assert chunks

    contents = [c.page_content for c in chunks]
    assert any("ITEM1_START" in c for c in contents)
    assert any("ITEM2_START" in c for c in contents)

    for c in contents:
        assert ("ITEM1_START" in c) == ("ITEM1_CONT" in c)
        assert ("ITEM2_START" in c) == ("ITEM2_CONT" in c)

