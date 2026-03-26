from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _SequentialRetriever:
    def __init__(self, docs_by_call: list[list[Document]]) -> None:
        self._docs_by_call = [list(items) for items in docs_by_call]
        self._call_index = 0
        self._last_debug_metrics: dict[str, object] = {}
        self.model_copy_updates: list[dict[str, object]] = []

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN001
        self.model_copy_updates.append(dict(update or {}))
        return self

    def invoke(self, _query: str) -> list[Document]:
        idx = min(self._call_index, len(self._docs_by_call) - 1)
        self._call_index += 1
        return list(self._docs_by_call[idx])


def _mk_doc(*, doc_id: str, chunk_index: int, score: float = 0.95) -> Document:
    chunk_id = f"{doc_id}:{chunk_index}"
    return Document(
        page_content=f"{chunk_id} content with evidence",
        id=chunk_id,
        metadata={
            "document_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_index": int(chunk_index),
            "source": "doc.txt",
            "page": 1,
            "score": float(score),
            "relevance_score": float(score),
        },
    )


def _disable_optional_features(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EVIDENCE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.0, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "mock answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)


@pytest.mark.asyncio
async def test_stream_chat_retries_retrieval_when_corrective_abstain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_MAX_ATTEMPTS", 2, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_PROFILE", "recall50", raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT", 3, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT_CAP", 8, raising=False)

    retriever = _SequentialRetriever(
        docs_by_call=[
            [],
            [_mk_doc(doc_id="doc-a", chunk_index=0)],
        ]
    )
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    engine = RAGEngine()
    done_metrics = None

    agen = engine.stream_chat(
        question="What does the evidence say?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=2,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="corrective-abstain-test",
    )

    try:
        async for event in agen:
            if event.get("type") == "done":
                done_metrics = (event.get("data") or {}).get("metrics") or {}
                break
    finally:
        await agen.aclose()

    assert retriever._call_index >= 2
    assert isinstance(done_metrics, dict)
    assert done_metrics.get("corrective_used") is True
    assert "abstain" in (done_metrics.get("corrective_reason_codes") or [])
    assert done_metrics.get("corrective_attempt_count") == 2

    retrieval_updates = [item for item in retriever.model_copy_updates if "k" in item]
    assert len(retrieval_updates) >= 2
    assert retrieval_updates[1].get("retrieval_profile") == "recall50"


@pytest.mark.asyncio
async def test_stream_chat_emits_quality_warning_when_faithfulness_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE", 0.8, raising=False)

    retriever = _SequentialRetriever(docs_by_call=[[_mk_doc(doc_id="doc-b", chunk_index=0)]])
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)
    monkeypatch.setattr(
        engine_mod,
        "compute_faithfulness_score",
        lambda **_kwargs: {
            "score": 0.4,
            "supported_claims": 1,
            "total_claims": 3,
            "unsupported_claims": ["unsupported"],
            "method": "test",
        },
        raising=True,
    )

    engine = RAGEngine()
    quality_warning = None

    agen = engine.stream_chat(
        question="Summarize the retrieved evidence.",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=2,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="corrective-quality-test",
    )

    try:
        async for event in agen:
            if event.get("type") == "quality_warning":
                quality_warning = event.get("data") or {}
            if event.get("type") == "done":
                break
    finally:
        await agen.aclose()

    assert quality_warning == {
        "kind": "faithfulness_low",
        "faithfulness_score": 0.4,
        "threshold": 0.8,
        "corrective_available": True,
    }
