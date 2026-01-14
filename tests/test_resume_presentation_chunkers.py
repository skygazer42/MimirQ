from langchain_core.documents import Document

from app.rag.chunking.strategies.presentation_slides import PresentationSlidesChunker
from app.rag.chunking.strategies.resume_structured import ResumeStructuredChunker


def test_resume_structured_chunker_preserves_offsets_and_section_metadata():
    text = (
        "# Education\n"
        "2018-2022 University of Example, B.S. Computer Science\n"
        "Coursework: Algorithms, Systems, Databases\n\n"
        "# Work Experience\n"
        "2022-2024 Example Corp — Software Engineer\n"
        "Built retrieval pipelines and evaluation tooling.\n\n"
        "# Skills\n"
        "Python, FastAPI, LangChain, Milvus, RAG\n\n"
        "Email: alice@example.com\n"
    )
    chunker = ResumeStructuredChunker(chunk_size=120, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "resume_structured"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("resume_section") for c in chunks)
    assert any((c.metadata or {}).get("resume_section_title") for c in chunks)


def test_presentation_slides_chunker_preserves_offsets_and_slide_metadata():
    text = (
        "# Slide 1: Intro\n"
        + ("Welcome " * 12).strip()
        + "\n\n"
        "---\n"
        "# Slide 2: Agenda\n"
        "- Problem\n"
        "- Approach\n"
        "- Results\n\n"
        "---\n"
        "# Slide 3: Q&A\n"
        + ("Questions " * 12).strip()
        + "\n"
    )
    chunker = PresentationSlidesChunker(chunk_size=120, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "presentation_slides"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("slide_index") == 0 for c in chunks)
    assert any((c.metadata or {}).get("slide_index") == 1 for c in chunks)
    assert any((c.metadata or {}).get("slide_title") for c in chunks)

