from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.retrieval import orchestrator


def test_authoritative_kg_rows_cannot_disappear_when_content_is_missing():
    chunk_id = uuid4()
    row = SimpleNamespace(id=chunk_id, document_id=uuid4(), content=None)
    with pytest.raises((TypeError, ValueError)):
        orchestrator._build_kg_injection_docs([chunk_id], [row], scores={}, features={})


def test_kg_injection_does_not_hide_authoritative_projection_failure(monkeypatch):
    monkeypatch.setattr(orchestrator.settings, "KG_ENABLED", True)
    monkeypatch.setattr(orchestrator.settings, "KG_CHAT_ENABLED", True)
    monkeypatch.setattr(orchestrator, "_resolve_kg_scope", lambda state: ([uuid4()], None, []))

    def fail_projection(ctx):
        raise ValueError("invalid stored content")

    monkeypatch.setattr(orchestrator, "_run_kg_injection", fail_projection)
    ctx = SimpleNamespace(state={"tenant_id": uuid4(), "enable_kg_chunk_injection": True})
    with pytest.raises(ValueError, match="invalid stored content"):
        orchestrator._run_retrieval_kg_injection_phase(ctx)
