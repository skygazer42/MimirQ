from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _StaticRetriever:
    def __init__(self) -> None:
        self._last_debug_metrics: dict[str, object] = {"provider": "test"}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _query: str) -> list[Document]:
        return [
            Document(
                page_content="evidence chunk",
                id="doc-1:0",
                metadata={
                    "document_id": "doc-1",
                    "chunk_id": "doc-1:0",
                    "chunk_index": 0,
                    "source": "doc.txt",
                    "page": 1,
                    "score": 0.9,
                    "relevance_score": 0.9,
                },
            )
        ]


@pytest.mark.asyncio
async def test_stream_chat_emits_status_and_retrieval_info_events_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EVIDENCE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "mock answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "RAG_STREAM_STATUS_EVENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_STREAM_RETRIEVAL_PROGRESS_ENABLED", True, raising=False)

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _StaticRetriever(), raising=True)

    engine = RAGEngine()
    status_events: list[dict[str, object]] = []
    retrieval_info_events: list[dict[str, object]] = []

    agen = engine.stream_chat(
        question="Give me the answer from the docs.",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=2,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="stream-status-test",
    )

    try:
        async for event in agen:
            if event.get("type") == "status":
                status_events.append(event.get("data") or {})
            elif event.get("type") == "retrieval_info":
                retrieval_info_events.append(event.get("data") or {})
            elif event.get("type") == "done":
                break
    finally:
        await agen.aclose()

    assert [item.get("stage") for item in status_events[:2]] == ["retrieval", "generation"]
    assert retrieval_info_events == [
        {
            "attempt": 1,
            "query_count": 1,
            "docs_count": 1,
            "citations_count": 1,
            "abstain_triggered": False,
            "retrieval_profile": None,
        }
    ]
