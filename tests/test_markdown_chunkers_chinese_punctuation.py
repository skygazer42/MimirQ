from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.markdown import MarkdownAwareChunker, MarkdownHeaderChunker


def test_markdown_header_chunker_fallback_splits_chinese_sentences_on_punctuation() -> None:
    text = "第一句。第二句。第三句。"
    chunker = MarkdownHeaderChunker(chunk_size=5, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])

    assert [c.page_content for c in chunks] == ["第一句。", "第二句。", "第三句。"]


def test_markdown_aware_chunker_splits_chinese_sentences_without_cross_sentence_bleed() -> None:
    text = "第一句。第二句。第三句。"
    chunker = MarkdownAwareChunker(chunk_size=5, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])
    assert chunks

    contents = [c.page_content for c in chunks]
    for c in contents:
        assert not ("第一句" in c and "第二" in c)
        assert not ("第二句" in c and "第三" in c)

