from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest


class _FakeQuery:
    def __init__(self, *, all_rows=None):  # noqa: ANN001
        self._all = all_rows

    def filter(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def all(self):  # noqa: ANN201
        return list(self._all or [])


class _FakeDB:
    def __init__(self, *, chunk_rows):  # noqa: ANN001
        self._chunk_rows = list(chunk_rows or [])

    def query(self, *args, **_k):  # noqa: ANN001
        if any(getattr(a, "__name__", "") == "DocumentChunk" for a in args):
            return _FakeQuery(all_rows=self._chunk_rows)
        return _FakeQuery(all_rows=[])


@pytest.mark.asyncio
async def test_rag_engine_injects_kg_event_chunks_into_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    log_records = []

    def _log_metrics(payload):  # noqa: ANN001
        log_records.append(payload)

    monkeypatch.setattr(engine_mod, "log_metrics", _log_metrics, raising=True)

    # Use a deterministic fake LLM; we stop after citations, but engine still selects an LLM.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    # Enable KG chunk injection.
    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 5, raising=False)

    # Avoid real TAG work.
    import app.services.chat_tag_service as tag_mod

    monkeypatch.setattr(
        tag_mod,
        "build_chat_tag_context_docs",
        lambda *_a, **_k: ([], {"enabled": False, "used": False, "reason": "not_run", "returned": 0}),
        raising=True,
    )

    # Stub retrieval: return no chunks from vector/BM25 so KG injection is the only source.
    class _FakeRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_k):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _FakeRetriever(), raising=True)

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    kg_calls = {"n": 0}

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None):  # noqa: ANN001
        kg_calls["n"] += 1
        return {
            "events": [
                {
                    "id": str(uuid.uuid4()),
                    "title": "Event 1",
                    "summary": "S",
                    "content": "C",
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "score": 0.9,
                }
            ]
        }

    monkeypatch.setattr(engine_mod, "kg_search", _fake_kg_search, raising=True)

    chunk = SimpleNamespace(
        id=chunk_id,
        tenant_id=tenant_id,
        document_id=doc_id,
        chunk_index=0,
        content="hello from kg chunk",
        page_number=1,
        start_char=10,
        end_char=20,
        doc_metadata={"source": "doc.pdf", "document_id": str(doc_id), "chunk_id": str(chunk_id)},
    )
    db = _FakeDB(chunk_rows=[chunk])

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="q",
        history=None,
        conversation_id=None,
        document_ids=[doc_id],
        tenant_id=tenant_id,
        account_id="u",
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=db,
    )

    citations = None
    done_metrics = None
    async for item in agen:
        if item.get("type") == "citations":
            citations = item.get("data")
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert isinstance(citations, list)
    assert len(citations) == 1
    assert citations[0].get("chunk_id") == str(chunk_id)
    assert citations[0].get("retrieval_role") == "kg"

    assert done_metrics.get("kg_chunks_injected") == 1
    assert kg_calls["n"] == 1

    rag_trace = next(r for r in log_records if r.get("event") == "rag_trace")
    assert (rag_trace.get("kg") or {}).get("chunks_injected") == 1
