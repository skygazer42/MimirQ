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


def test_auto_chunker_selects_qa_pairs_for_qa_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "Q: What is RAG?\n"
        "A: Retrieval-Augmented Generation.\n\n"
        "Q: Why chunk?\n"
        "A: Better retrieval.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "qa_pairs"


def test_auto_chunker_selects_transcript_for_dialogue_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "Host: Hello everyone.\n"
        "Guest: Thanks.\n"
        "Host: Let's begin.\n"
        "Guest: Sure.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "transcript"


def test_auto_chunker_selects_paper_for_paper_like_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "Abstract\n"
        + ("a" * 420)
        + "\nIntroduction\n"
        + ("b" * 420)
        + "\nReferences\n"
        + ("c" * 80)
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "paper"


def test_auto_chunker_selects_outline_for_numbered_outline_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "1. Chapter One\n"
        "This is some content under chapter one.\n\n"
        "2. Chapter Two\n"
        "This is some content under chapter two.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "outline"

