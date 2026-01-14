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


def test_auto_chunker_selects_email_thread_for_email_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "From: Alice <a@example.com>\n"
        "To: Bob <b@example.com>\n"
        "Subject: Re: Hello\n"
        "Date: Mon, 1 Jan 2024 10:00:00 +0000\n"
        "\n"
        "Hi Bob,\n"
        "Here is the update: " + ("x" * 80) + "\n"
        "\n"
        "-----Original Message-----\n"
        "From: Bob <b@example.com>\n"
        "To: Alice <a@example.com>\n"
        "Subject: Hello\n"
        "Date: Mon, 1 Jan 2024 09:00:00 +0000\n"
        "\n"
        "Hi Alice,\n"
        "Thanks! " + ("y" * 60) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "email_thread"


def test_auto_chunker_selects_sop_steps_for_procedure_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "操作步骤如下：\n"
        "步骤一：打开应用。" + ("a" * 90) + "\n"
        "步骤二：登录账号。" + ("b" * 90) + "\n"
        "步骤三：完成设置。" + ("c" * 90) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "sop_steps"


def test_auto_chunker_selects_glossary_for_glossary_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "RAG: Retrieval-Augmented Generation " + ("r" * 40) + "\n"
        "LLM: Large Language Model " + ("l" * 40) + "\n"
        "Embedding: Vector representation " + ("e" * 40) + "\n"
        "Chunk: A piece of text " + ("c" * 40) + "\n"
        "Retriever: Fetches relevant chunks " + ("t" * 40) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "glossary"


def test_auto_chunker_selects_laws_for_laws_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "第一章 总则\n"
        "第一条【目的】" + ("法" * 120) + "\n"
        "第二条【适用范围】" + ("规" * 120) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "laws_structured"


def test_auto_chunker_selects_book_for_book_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "Part I: Getting Started\n"
        "Chapter 1: Intro\n"
        + ("x" * 120)
        + "\n"
        "Chapter 2: Basics\n"
        + ("y" * 120)
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "book_structured"

