from langchain_core.documents import Document

from app.rag.chunking.strategies.book_structured import BookStructuredChunker
from app.rag.chunking.strategies.email_thread import EmailThreadChunker
from app.rag.chunking.strategies.laws_structured import LawsStructuredChunker


def test_book_structured_chunker_preserves_offsets_and_path():
    text = (
        "Part I: Getting Started\n"
        "Chapter 1: Intro\n"
        "Some intro content.\n\n"
        "Chapter 2: Basics\n"
        "More content here.\n"
    )
    chunker = BookStructuredChunker(chunk_size=120, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "book_structured"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("book_kind") == "chapter" for c in chunks)
    assert any((c.metadata or {}).get("book_path") for c in chunks)


def test_laws_structured_chunker_preserves_offsets_and_article_metadata():
    text = (
        "第一章 总则\n"
        "第一条【目的】为了规范……\n"
        "第二条【适用范围】本法适用于……\n"
        "（一）条款细则一。\n"
        "（二）条款细则二。\n"
    )
    chunker = LawsStructuredChunker(chunk_size=160, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "laws_structured"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("law_kind") == "article" for c in chunks)
    assert any((c.metadata or {}).get("law_path") for c in chunks)


def test_email_thread_chunker_preserves_offsets_and_message_metadata():
    text = (
        "From: Alice <a@example.com>\n"
        "To: Bob <b@example.com>\n"
        "Subject: Re: Hello\n"
        "Date: Mon, 1 Jan 2024 10:00:00 +0000\n"
        "\n"
        "Hi Bob,\n"
        "See below.\n"
        "\n"
        "-----Original Message-----\n"
        "From: Bob <b@example.com>\n"
        "To: Alice <a@example.com>\n"
        "Subject: Hello\n"
        "Date: Mon, 1 Jan 2024 09:00:00 +0000\n"
        "\n"
        "Hi Alice!\n"
    )
    chunker = EmailThreadChunker(chunk_size=220, chunk_overlap=40)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "email_thread"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    # At least one chunk should contain both messages (or metadata about subjects).
    assert any(int((c.metadata or {}).get("email_message_count") or 0) >= 1 for c in chunks)
    subjects = []
    for c in chunks:
        subjects.extend((c.metadata or {}).get("email_subjects") or [])
    assert any("Hello" in s for s in subjects)

