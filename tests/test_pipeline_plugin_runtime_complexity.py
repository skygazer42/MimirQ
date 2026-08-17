from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.rag.pipeline_plugins.runtime import (
    PythonPipelinePluginError,
    _coerce_kg_event,
    _invoke_plugin,
)


def test_invoke_plugin_maps_supported_names_and_context_values() -> None:
    documents = [Document(page_content="body", metadata={})]
    params = {"mode": "strict"}
    context = {"chunk_size": 256, "chunk_overlap": 32, "stage": "chunking"}

    def plugin(items, params, context, chunk_size, chunk_overlap, stage):
        return items, params, context, chunk_size, chunk_overlap, stage

    assert _invoke_plugin(
        plugin,
        documents=documents,
        params=params,
        context=context,
    ) == (documents, params, context, 256, 32, "chunking")


def test_invoke_plugin_falls_back_to_documents_for_unknown_required_argument() -> None:
    documents = [Document(page_content="body", metadata={})]

    def plugin(payload):
        return payload

    assert _invoke_plugin(plugin, documents=documents, params={}, context={}) is documents


def test_coerce_kg_event_inherits_scope_and_builds_entities() -> None:
    document_id = uuid4()
    chunk_id = uuid4()
    documents = [
        Document(
            page_content="source",
            metadata={
                "document_id": str(document_id),
                "source": "guide.pdf",
                "chunk_index": 4,
            },
            id=str(chunk_id),
        )
    ]

    event = _coerce_kg_event(
        {
            "summary": "Policy approval event",
            "references": {"source": "override.pdf"},
            "extra_data": {"origin": "plugin"},
            "metadata": {"category": "policy"},
            "entities": [
                {
                    "name": "Finance Team",
                    "normalized_name": "finance team",
                    "type": "department",
                    "vector": [1, "2.5"],
                    "evidence_start_char": "7",
                },
                {"name": "   "},
            ],
        },
        documents=documents,
        plugin_ref="demo.plugin:build_kg_events",
        index=0,
    )

    assert event is not None
    assert event.title == "Policy approval event"
    assert event.summary == "Policy approval event"
    assert event.content == "Policy approval event"
    assert event.document_id == document_id
    assert event.chunk_id == chunk_id
    assert event.references == {
        "source": "override.pdf",
        "chunk_index": 4,
        "kg_python_plugin": "demo.plugin:build_kg_events",
    }
    assert event.extra_data == {
        "origin": "plugin",
        "kg_python_plugin": "demo.plugin:build_kg_events",
    }
    assert len(event.entities) == 1
    assert event.entities[0].normalized_name == "finance team"
    assert event.entities[0].vector == [1.0, 2.5]
    assert event.entities[0].evidence_start_char == 7


def test_coerce_kg_event_rejects_unsupported_entity_shape() -> None:
    with pytest.raises(PythonPipelinePluginError, match="unsupported entity at event 2, index 0"):
        _coerce_kg_event(
            {"title": "event", "entities": ["invalid"]},
            documents=[],
            plugin_ref="demo.plugin:build_kg_events",
            index=2,
        )
