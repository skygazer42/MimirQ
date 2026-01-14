from langchain_core.documents import Document

from app.rag.chunking.strategies.qa_pairs import QAPairsChunker
from app.rag.chunking.strategies.transcript import TranscriptChunker


def test_transcript_chunker_preserves_offsets_and_speaker_metadata():
    text = (
        "Host: Welcome everyone to the meeting.\n"
        "Guest: Thanks for inviting me.\n"
        "Host: Let's start with the agenda.\n"
        "Guest: The project is on track.\n"
    )
    chunker = TranscriptChunker(chunk_size=80, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert len(chunks) >= 3
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "transcript"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("turn_count") or 0) >= 1
        assert isinstance(meta.get("speakers"), list)

    assert any("Host" in ((c.metadata or {}).get("speakers") or []) for c in chunks)
    assert any("Guest" in ((c.metadata or {}).get("speakers") or []) for c in chunks)


def test_qa_pairs_chunker_preserves_offsets_and_pairs():
    text = (
        "Q: What is RAG?\n"
        "A: Retrieval-Augmented Generation.\n\n"
        "Q: Why chunk documents?\n"
        "A: To improve retrieval granularity.\n"
    )
    chunker = QAPairsChunker(chunk_size=120, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "qa_pairs"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("qa_pair_count") or 0) >= 1

    previews = []
    for c in chunks:
        previews.extend((c.metadata or {}).get("qa_question_previews") or [])
    assert any("What is RAG?" in p for p in previews)
