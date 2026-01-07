from langchain_core.documents import Document

from app.rag.chunking.strategies.auto import AutoChunker


def test_auto_chunker_selects_markdown_for_markdownish_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    docs = [Document(page_content="# Title\n\nHello world.\n", metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "markdown_aware"


def test_auto_chunker_selects_json_for_json_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    docs = [Document(page_content='{"a": 1, "b": 2}', metadata={"file_type": "json"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "json"


def test_auto_chunker_selects_semantic_for_long_plain_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = ("hello world. " * 200).strip()
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "semantic_sentence"

