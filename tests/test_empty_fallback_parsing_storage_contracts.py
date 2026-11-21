from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.query.expand import coerce_expansion_rules, generate_dictionary_expansions
from app.query.normalize import normalize_query
from app.rag.ingestion.indexing.support.parse_io import _deserialize_documents_from_parse_cache
from app.rag.ingestion.parsing.artifact_stats import compute_document_analytics
from app.rag.ingestion.parsing.quality.text_quality import score_parsed_text_quality
from app.storage.vector.factory import MemoryVectorStore
from app.storage.vector.milvus import _prepare_adapter_vector_payload, _prepare_document_write_payload


@pytest.mark.parametrize("store_class", [MemoryVectorStore])
def test_vector_ingestion_requires_chunk_content(monkeypatch, store_class):
    from app.infrastructure.config import settings

    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "deterministic_test")
    store = store_class()

    with pytest.raises(KeyError, match="content"):
        store.add_documents([{"metadata": {}}], document_id=UUID(int=2), tenant_id=UUID(int=1))

    assert store.storage == []


@pytest.mark.parametrize("prepare", [_prepare_adapter_vector_payload, _prepare_document_write_payload])
@pytest.mark.parametrize("content", [None, 0, False])
def test_milvus_ingestion_rejects_non_text_content(prepare, content):
    kwargs = (
        {"reserved_fields": set()}
        if prepare is _prepare_adapter_vector_payload
        else {"document_id": UUID(int=2), "tenant_id": UUID(int=1)}
    )
    with pytest.raises(TypeError):
        prepare([{"id": "chunk", "content": content, "metadata": {}}], **kwargs)


@pytest.mark.parametrize("payload", [{}, {"page_content": None, "metadata": {}}])
def test_parse_cache_does_not_invent_required_page_text(payload):
    with pytest.raises(ValueError, match="requires text and object metadata"):
        _deserialize_documents_from_parse_cache([payload])


def test_parse_cache_keeps_optional_cache_miss_and_empty_text():
    assert _deserialize_documents_from_parse_cache(None) is None
    assert _deserialize_documents_from_parse_cache([]) == []
    assert _deserialize_documents_from_parse_cache([{"page_content": "", "metadata": {}}]) == [
        Document(page_content="")
    ]


@pytest.mark.parametrize("operation", [normalize_query, score_parsed_text_quality])
def test_required_query_and_quality_text_rejects_none(operation):
    with pytest.raises((AttributeError, TypeError)):
        operation(None)


def test_document_analytics_requires_markdown_text():
    with pytest.raises((AttributeError, TypeError)):
        compute_document_analytics(markdown=None)


def test_dictionary_expansion_requires_query_text():
    with pytest.raises(AttributeError):
        generate_dictionary_expansions(query=None, rules={"SLO": ["service level objective"]})


@pytest.mark.parametrize(
    "rules, expected", [({0: [False, None]}, {"0": ["False"]}), ({False: [0, None]}, {"False": ["0"]})]
)
def test_dictionary_expansion_preserves_falsy_scalar_tokens_and_skips_nulls(rules, expected):
    assert coerce_expansion_rules(rules) == expected
