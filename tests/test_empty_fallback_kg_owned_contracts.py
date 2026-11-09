from collections import Counter
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models.document import DocumentChunk
from app.rag.kg.api.routes_support.projection import _kg_event_node, _kg_relation_link
from app.rag.kg.extraction.extractor import _document_from_chunk, _populate_chunk_content_maps
from app.rag.kg.extraction.processor import EventProcessor, _collect_event_entities
from app.rag.kg.models import KgRelation, KgSourceEvent
from app.rag.kg.repository import _format_lexical_event
from app.rag.kg.search.ranking.features import event_document_id, event_search_text
from app.rag.kg.search.tracker import build_event_node


def test_kg_chunk_identity_keeps_a_zero_chunk_index():
    chunk = DocumentChunk(id=UUID(int=2), document_id=UUID(int=1), chunk_index=0, content="first", doc_metadata={})
    state = SimpleNamespace(
        resolved_chunks=[chunk], chunk_hash_by_id={}, chunk_len_by_id={}, chunk_key_by_id={}
    )

    _populate_chunk_content_maps(state)

    assert state.chunk_key_by_id[chunk.id] == "0"


def test_kg_document_adapter_requires_the_actual_chunk_body():
    chunk = DocumentChunk(id=UUID(int=2), document_id=UUID(int=1), chunk_index=0, content=None, doc_metadata={})

    with pytest.raises(ValidationError):
        _document_from_chunk(chunk)


def test_kg_ranking_does_not_invent_a_missing_event_summary():
    with pytest.raises(AttributeError, match="summary"):
        event_search_text(SimpleNamespace(title="Policy", content="Document body"))


@pytest.mark.parametrize("field", ["title", "summary", "content"])
def test_kg_ranking_rejects_null_required_event_text(field):
    values = {"title": "title", "summary": "summary", "content": "body"}
    values[field] = None

    with pytest.raises(TypeError):
        event_search_text(KgSourceEvent(**values))


def test_kg_relation_projection_keeps_absent_optional_provenance():
    relation = KgRelation(
        subject_entity_id=UUID(int=1), object_entity_id=UUID(int=2), predicate="uses", confidence=0.7,
        document_id=None, chunk_id=None, event_id=None,
    )

    link = _kg_relation_link(relation)

    assert link["meta"]["document_id"] is None
    assert link["meta"]["chunk_id"] is None
    assert link["meta"]["event_id"] is None


def test_kg_event_projection_requires_the_persisted_event_title():
    event = KgSourceEvent(id=UUID(int=1), title=None, summary="summary", content="body")

    with pytest.raises(AttributeError):
        _kg_event_node(event, Counter())


@pytest.mark.parametrize("entity", [{"name": None}, {"name": 0}, {"name": False}])
def test_kg_entity_payload_rejects_invalid_external_name_values(entity):
    assert _collect_event_entities([entity]) == []


def test_kg_entity_payload_keeps_the_schema_optional_missing_name():
    assert _collect_event_entities([{}]) == []


def test_kg_ranking_keeps_a_missing_optional_document_identity():
    event = KgSourceEvent(id=UUID(int=1), document_id=None, title="title", summary="summary", content="body")

    assert event_document_id(event) is None


@pytest.mark.parametrize("payload", [{"summary": "summary"}, {"title": "title", "summary": None}, {"title": "title", "summary": False}])
@pytest.mark.asyncio
async def test_kg_event_extraction_rejects_invalid_external_response_text(payload):
    class Client:
        async def chat_with_schema(self, messages, **kwargs):
            return {"events": [payload]}

    chunk = DocumentChunk(id=UUID(int=1), content="policy body", doc_metadata={})

    assert await EventProcessor(Client()).extract_from_sections([chunk], batch_index=0) == []


@pytest.mark.parametrize("provenance, expected", [(None, None), (UUID(int=2), "00000000-0000-0000-0000-000000000002")])
def test_kg_lexical_event_preserves_optional_provenance(provenance, expected):
    event = KgSourceEvent(
        id=UUID(int=1), title="Policy", summary="summary", content="body",
        document_id=provenance, chunk_id=provenance,
    )

    item = _format_lexical_event(event, terms=["policy"], tenant_id=UUID(int=3))

    assert item["document_id"] == expected
    assert item["chunk_id"] == expected


def test_kg_trace_node_passes_scalar_text_to_its_serializer(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "KG_SEARCH_NODE_TEXT_MAX_CHARS", 1000)

    node = build_event_node({"id": "event-1", "title": 0, "content": False})

    assert node["content"] == "0"
    assert node["description"] == "False"


@pytest.mark.parametrize("title", [0, False])
def test_kg_trace_identity_requires_text_when_no_event_id_is_available(title):
    with pytest.raises(TypeError):
        build_event_node({"title": title})
