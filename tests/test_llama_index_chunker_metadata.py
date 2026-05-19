from __future__ import annotations

from langchain_core.documents import Document


def test_llama_index_chunker_ignores_metadata_when_splitting(monkeypatch) -> None:
    from app.core.config import settings
    from app.rag.chunking.strategies.llama_index import LlamaIndexChunker

    monkeypatch.setattr(settings, "LLAMA_INDEX_ENABLED", True, raising=False)

    chunker = LlamaIndexChunker(chunk_size=250, chunk_overlap=0)
    source = Document(
        page_content=(
            "Acme Robotics signed a supply agreement with Beta Logistics. "
            "Alice Chen owns the delivery event."
        ),
        metadata={
            "parser_backend": "deepdoc",
            "source": "metadata-heavy.pdf",
            "pipeline_hash": "x" * 64,
            "doc_pipeline_key": "document-id:" + ("y" * 64),
            "long_audit_field": "z" * 400,
        },
    )

    chunks = chunker.split_documents([source])

    assert chunks
    assert chunks[0].metadata["parser_backend"] == "deepdoc"
    assert chunks[0].metadata["chunk_strategy"] == "llama_index"


def test_llama_index_hierarchical_chunker_ignores_metadata_when_splitting(monkeypatch) -> None:
    from app.core.config import settings
    from app.rag.chunking.strategies.llama_index import LlamaIndexHierarchicalChunker

    monkeypatch.setattr(settings, "LLAMA_INDEX_ENABLED", True, raising=False)

    chunker = LlamaIndexHierarchicalChunker(chunk_size=250, chunk_overlap=0)
    source = Document(
        page_content=(
            "Acme Robotics signed a supply agreement with Beta Logistics. "
            "Alice Chen owns the delivery event. "
            "The Q3 delivery plan includes 120 inspection robots."
        ),
        metadata={
            "parser_backend": "deepdoc",
            "source": "metadata-heavy.pdf",
            "pipeline_hash": "x" * 64,
            "doc_pipeline_key": "document-id:" + ("y" * 64),
            "long_audit_field": "z" * 400,
        },
    )

    chunks = chunker.split_documents([source])

    assert chunks
    assert chunks[0].metadata["parser_backend"] == "deepdoc"
    assert chunks[0].metadata["chunk_strategy"] == "llama_index_hierarchical"
