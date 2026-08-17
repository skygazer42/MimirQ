import threading
import uuid

import pytest
from langchain_core.documents import Document


class _SequentialRetriever:
    def __init__(self, docs_by_call: list[list[Document]]) -> None:
        self._docs_by_call = [list(items) for items in docs_by_call]
        self._call_index = 0
        self._last_debug_metrics: dict[str, object] = {}
        self.model_copy_updates: list[dict[str, object]] = []
        self.invoke_thread_ids: list[int] = []

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN001
        self.model_copy_updates.append(dict(update or {}))
        return self

    def invoke(self, _query: str) -> list[Document]:
        self.invoke_thread_ids.append(threading.get_ident())
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
    monkeypatch.setattr(settings, "RAG_STREAM_RETRIEVAL_PROGRESS_ENABLED", True, raising=False)


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
    loop_thread_id = threading.get_ident()
    done_metrics = None
    retrieval_info_events: list[dict[str, object]] = []

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
            if event.get("type") == "retrieval_info":
                retrieval_info_events.append(dict(event.get("data") or {}))
            if event.get("type") == "done":
                done_metrics = (event.get("data") or {}).get("metrics") or {}
                break
    finally:
        await agen.aclose()

    assert retriever._call_index >= 2
    assert len(retriever.invoke_thread_ids) >= 2
    assert all(thread_id != loop_thread_id for thread_id in retriever.invoke_thread_ids)
    assert retrieval_info_events == [
        {
            "attempt": 1,
            "query_count": 1,
            "docs_count": 0,
            "citations_count": 0,
            "abstain_triggered": True,
            "retrieval_profile": None,
        },
        {
            "attempt": 2,
            "query_count": 2,
            "docs_count": 1,
            "citations_count": 1,
            "abstain_triggered": False,
            "retrieval_profile": "recall50",
        },
    ]
    assert isinstance(done_metrics, dict)
    assert done_metrics.get("corrective_used") is True
    assert "abstain" in (done_metrics.get("corrective_reason_codes") or [])
    assert done_metrics.get("corrective_attempt_count") == 2

    retrieval_updates = [item for item in retriever.model_copy_updates if "k" in item]
    assert len(retrieval_updates) >= 2
    assert retrieval_updates[1].get("retrieval_profile") == "recall50"


@pytest.mark.asyncio
async def test_stream_chat_serial_retrieval_failure_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_ENABLED", False, raising=False)
    retriever = _SequentialRetriever(docs_by_call=[[]])
    retriever._last_debug_metrics = {
        "all_retrieval_channels_failed": True,
        "retrieval_degraded_reasons": [
            {"channel": "bm25", "error_type": "RuntimeError"},
            {"channel": "vector", "error_type": "ConnectionError"},
        ],
    }
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    stream = RAGEngine().stream_chat(
        question="What failed?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        top_k=2,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        request_id="serial-retrieval-failure-test",
    )
    error = None
    try:
        async for event in stream:
            if event.get("type") == "error":
                error = event.get("data") or {}
                break
    finally:
        await stream.aclose()

    assert error == {
        "message": "retrieval failed: all retrieval channels failed: bm25:RuntimeError, vector:ConnectionError"
    }


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


@pytest.mark.asyncio
async def test_stream_chat_does_not_split_redacted_pii_across_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    raw_id = "138001380001234567"
    response = ("A" * 140) + raw_id + ("B" * 140)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", response, raising=False)
    monkeypatch.setattr(settings, "PII_REDACTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PII_REDACTION_MASK", "[REDACTED]", raising=False)
    monkeypatch.setattr(settings, "PII_STREAM_HOLDBACK_CHARS", 128, raising=False)
    monkeypatch.setattr(settings, "OUTPUT_GUARD_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SHOW_IMAGE_IN_ANSWER", False, raising=False)
    monkeypatch.setattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        engine_mod,
        "hybrid_retriever",
        _SequentialRetriever(docs_by_call=[[_mk_doc(doc_id="doc-pii", chunk_index=0)]]),
        raising=True,
    )

    stream = RAGEngine().stream_chat(
        question="Return the test response.",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        visible_evidence_only=False,
        request_id="pii-stream-boundary-test",
    )
    token_text = ""
    event_types: list[str] = []
    try:
        async for event in stream:
            event_types.append(str(event.get("type")))
            if event.get("type") == "token":
                token_text += str((event.get("data") or {}).get("content") or "")
            if event.get("type") == "done":
                break
    finally:
        await stream.aclose()

    assert token_text == ("A" * 140) + "[REDACTED]" + ("B" * 140)
    assert raw_id not in token_text
    assert event_types[-2:] == ["token", "done"]
