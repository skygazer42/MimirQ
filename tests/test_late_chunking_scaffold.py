from __future__ import annotations

from langchain_core.documents import Document


def test_late_chunking_chunker_marks_document_scope_pooling_metadata() -> None:
    from app.rag.chunking.strategies.late_chunking import LateChunkingChunker

    chunker = LateChunkingChunker(chunk_size=80, chunk_overlap=0)
    out = chunker.split_documents(
        [
            Document(
                page_content=(
                    "Alpha service provisions accounts. "
                    "Beta worker syncs ledgers. "
                    "Gamma notifier sends callbacks."
                ),
                metadata={"source": "ops.md"},
            )
        ]
    )

    assert out
    assert all((doc.metadata or {}).get("chunk_strategy") == "late_chunking" for doc in out)
    assert all((doc.metadata or {}).get("late_chunking_enabled") is True for doc in out)
    assert all((doc.metadata or {}).get("late_chunking_pooling") == "mean" for doc in out)
    assert all((doc.metadata or {}).get("late_chunking_scope") == "document" for doc in out)


def test_late_chunking_jina_chunker_marks_provider_specific_metadata() -> None:
    from app.rag.chunking.strategies.late_chunking_jina import LateChunkingJinaChunker

    chunker = LateChunkingJinaChunker(chunk_size=80, chunk_overlap=0)
    out = chunker.split_documents([Document(page_content="Alpha. Beta. Gamma.", metadata={})])

    assert out
    assert all((doc.metadata or {}).get("chunk_strategy") == "late_chunking_jina" for doc in out)
    assert all((doc.metadata or {}).get("late_chunking_provider") == "jina_v3" for doc in out)
    assert all((doc.metadata or {}).get("late_chunking_boundary_mode") == "boundary_pooling" for doc in out)


def test_chunker_factory_supports_late_chunking_aliases() -> None:
    from app.rag.chunking.factory import chunker_factory
    from app.rag.chunking.strategies.late_chunking import LateChunkingChunker
    from app.rag.chunking.strategies.late_chunking_jina import LateChunkingJinaChunker

    assert isinstance(chunker_factory.get_chunker("late_chunking", chunk_size=100, chunk_overlap=10), LateChunkingChunker)
    assert isinstance(
        chunker_factory.get_chunker("late_chunking_jina", chunk_size=100, chunk_overlap=10),
        LateChunkingJinaChunker,
    )
