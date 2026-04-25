from __future__ import annotations

from uuid import UUID

from app.core.config import settings
from app.services.indexer import Indexer
from app.types.indexing import ChunkInput, IndexingOptions


def test_indexer_injects_contextual_prefix_into_embedding_text_when_enabled() -> None:
    class _DummyIndexer:
        vector_docs_calls: list[list[dict]] = []

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return True

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs_calls.append(list(vector_docs))
            return ["vid"] * len(vector_docs)

        def _persist_document_chunks(self, **_kwargs):  # noqa: ANN001
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()

    doc_id = UUID(int=1)
    tenant_id = UUID(int=2)
    chunks = [
        ChunkInput(
            content="hello world",
            metadata={
                "title": "Doc Title",
                "header_path": "H1 / H2",
            },
        )
    ]
    options = IndexingOptions(
        chunk_vector_enabled=True,
        bm25_index_enabled=False,
        embedding_context_prefix_enabled=False,
        embedding_contextual_retrieval_enabled=True,
        embedding_field_aware_enabled=False,
    )

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=doc_id,
        tenant_id=tenant_id,
        chunks=chunks,
        default_source="orig.pdf",
        commit=False,
        options=options,
    )

    assert dummy.vector_docs_calls
    body_docs = dummy.vector_docs_calls[0]
    assert len(body_docs) == 1
    embed_text = str(body_docs[0].get("content") or "")
    assert embed_text
    assert embed_text.startswith("Excerpt from document 'Doc Title'.")
    assert "hello world" in embed_text


def test_indexer_uses_llm_contextual_enrichment_when_enabled(monkeypatch) -> None:
    class _DummyIndexer:
        vector_docs_calls: list[list[dict]] = []

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return True

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs_calls.append(list(vector_docs))
            return ["vid"] * len(vector_docs)

        def _persist_document_chunks(self, **_kwargs):  # noqa: ANN001
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    monkeypatch.setattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_ENRICHMENT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS", 120, raising=False)
    monkeypatch.setattr(
        "app.services.indexer._build_llm_contextual_summary",
        lambda **_kwargs: "LLM summary sentence.",
    )

    dummy = _DummyIndexer()
    options = IndexingOptions(
        chunk_vector_enabled=True,
        bm25_index_enabled=False,
        embedding_context_prefix_enabled=False,
        embedding_contextual_retrieval_enabled=True,
        embedding_field_aware_enabled=False,
    )
    chunks = [ChunkInput(content="hello world", metadata={"title": "Doc Title", "header_path": "H1 / H2"})]

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=UUID(int=11),
        tenant_id=UUID(int=22),
        chunks=chunks,
        default_source="orig.pdf",
        commit=False,
        options=options,
    )

    body_docs = dummy.vector_docs_calls[0]
    embed_text = str(body_docs[0].get("content") or "")
    assert embed_text.startswith("LLM summary sentence.")
    assert "hello world" in embed_text


def test_indexer_contextual_retrieval_lazy_mode_skips_prefix_without_gap_signal() -> None:
    class _DummyIndexer:
        vector_docs_calls: list[list[dict]] = []

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return True

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs_calls.append(list(vector_docs))
            return ["vid"] * len(vector_docs)

        def _persist_document_chunks(self, **_kwargs):  # noqa: ANN001
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()
    options = IndexingOptions(
        chunk_vector_enabled=True,
        bm25_index_enabled=False,
        embedding_context_prefix_enabled=False,
        embedding_contextual_retrieval_enabled=True,
        embedding_contextual_retrieval_lazy_mode=True,
        embedding_field_aware_enabled=False,
    )
    chunks = [ChunkInput(content="hello world", metadata={"title": "Doc Title", "header_path": "H1 / H2"})]

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=UUID(int=31),
        tenant_id=UUID(int=32),
        chunks=chunks,
        default_source="orig.pdf",
        commit=False,
        options=options,
    )

    body_docs = dummy.vector_docs_calls[0]
    embed_text = str(body_docs[0].get("content") or "")
    assert embed_text == "hello world"


def test_indexer_contextual_retrieval_lazy_mode_applies_prefix_when_gap_signal_present() -> None:
    class _DummyIndexer:
        vector_docs_calls: list[list[dict]] = []

        def _resolve_chunk_vector_enabled(self, _options):  # noqa: ANN001
            return True

        def _resolve_bm25_enabled(self, _options):  # noqa: ANN001
            return False

        def _index_chunk_vectors(self, vector_docs, **_kwargs):  # noqa: ANN001
            self.vector_docs_calls.append(list(vector_docs))
            return ["vid"] * len(vector_docs)

        def _persist_document_chunks(self, **_kwargs):  # noqa: ANN001
            return []

        def _update_bm25_for_chunks(self, **_kwargs):  # noqa: ANN001
            return None

    dummy = _DummyIndexer()
    options = IndexingOptions(
        chunk_vector_enabled=True,
        bm25_index_enabled=False,
        embedding_context_prefix_enabled=False,
        embedding_contextual_retrieval_enabled=True,
        embedding_contextual_retrieval_lazy_mode=True,
        embedding_field_aware_enabled=False,
    )
    chunks = [
        ChunkInput(
            content="hello world",
            metadata={
                "title": "Doc Title",
                "header_path": "H1 / H2",
                "evidence_gap": {"has_gap": True, "severity": "high"},
            },
        )
    ]

    Indexer.index_chunks(  # type: ignore[misc]
        dummy,
        document_id=UUID(int=41),
        tenant_id=UUID(int=42),
        chunks=chunks,
        default_source="orig.pdf",
        commit=False,
        options=options,
    )

    body_docs = dummy.vector_docs_calls[0]
    embed_text = str(body_docs[0].get("content") or "")
    assert embed_text.startswith("Excerpt from document 'Doc Title'.")
    assert "hello world" in embed_text
