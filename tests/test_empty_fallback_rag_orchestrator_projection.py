from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.documents.records import DocumentChunk
from app.rag.retrieval.stages import knowledge_graph


def test_authoritative_kg_rows_cannot_disappear_when_content_is_missing():
    chunk_id = uuid4()
    row = DocumentChunk(id=chunk_id, document_id=uuid4(), content=None, doc_metadata={})
    with pytest.raises((TypeError, ValueError)):
        knowledge_graph._build_kg_injection_docs([chunk_id], [row], scores={}, features={})


def test_kg_injection_reports_projection_failure_and_preserves_main_candidates(monkeypatch):
    monkeypatch.setattr(knowledge_graph.settings, "KG_ENABLED", True)
    monkeypatch.setattr(knowledge_graph.settings, "KG_CHAT_ENABLED", True)
    monkeypatch.setattr(knowledge_graph, "_resolve_kg_scope", lambda state: ([uuid4()], None, []))

    def fail_projection(ctx):
        raise ValueError("invalid stored content")

    monkeypatch.setattr(knowledge_graph, "_run_kg_injection", fail_projection)
    main_document = object()
    ctx = SimpleNamespace(
        state={"tenant_id": uuid4(), "enable_kg_chunk_injection": True, "kg_chunk_injection_max_chunks": 1},
        docs=[main_document],
    )
    assert knowledge_graph._run_retrieval_kg_injection_phase(ctx) is None
    assert ctx.kg_chunk_injection_error == "invalid stored content"
    assert ctx.kg_chunks_injected == 0
    assert ctx.docs == [main_document] and ctx.docs[0] is main_document
