from langchain_core.documents import Document

from app.rag.chunking.strategies.glossary import GlossaryChunker
from app.rag.chunking.strategies.sentence_window import SentenceWindowChunker
from app.rag.chunking.strategies.sop_steps import SOPStepsChunker


def test_sop_steps_chunker_preserves_offsets_and_step_metadata():
    text = (
        "操作步骤如下：\n"
        "步骤一：打开应用。\n"
        "步骤二：登录账号。\n"
        "步骤三：完成设置。\n"
    )
    chunker = SOPStepsChunker(chunk_size=120, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "sop_steps"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("sop_step_no") for c in chunks)


def test_glossary_chunker_preserves_offsets_and_terms_metadata():
    text = (
        "RAG: Retrieval-Augmented Generation\n"
        "LLM: Large Language Model\n"
        "Embedding: Vector representation\n"
        "Chunk: A piece of text\n"
        "Retriever: Fetches relevant chunks\n"
    )
    chunker = GlossaryChunker(chunk_size=160, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "glossary"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    terms = []
    for c in chunks:
        terms.extend((c.metadata or {}).get("glossary_terms") or [])
    assert "RAG" in terms


def test_sentence_window_chunker_preserves_offsets_and_sentence_count():
    text = "Hello world. This is a test. Another sentence here! End."
    chunker = SentenceWindowChunker(chunk_size=30, chunk_overlap=10)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "sentence_window"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("sentence_count") or 0) >= 1

