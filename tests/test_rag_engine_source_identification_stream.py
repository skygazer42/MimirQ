from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _SingleRetriever:
    def __init__(self, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict[str, object] = {}

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN001, ANN201
        return self

    def invoke(self, _query: str) -> list[Document]:
        return list(self._docs)


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
    monkeypatch.setattr(settings, "RAG_AGENTIC_MODE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "OUTPUT_GUARD_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "INPUT_GUARD_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings,
        "LLM_MOCK_RESPONSE",
        'The paper is "deep-residual-learning_1512.03385.pdf".',
        raising=False,
    )


@pytest.mark.asyncio
async def test_stream_chat_source_identification_prefers_title_over_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    doc_id = str(uuid.uuid4())
    doc = Document(
        page_content=(
            "Deep Residual Learning for Image Recognition\n"
            "We present a residual learning framework and shortcut connections to address degradation."
        ),
        id=f"{doc_id}:0",
        metadata={
            "document_id": doc_id,
            "chunk_id": f"{doc_id}:0",
            "chunk_index": 0,
            "source": "deep-residual-learning_1512.03385.pdf",
            "filename": "deep-residual-learning_1512.03385.pdf",
            "document_title": "Deep Residual Learning for Image Recognition",
            "score": 0.98,
            "relevance_score": 0.98,
        },
    )
    monkeypatch.setattr(engine_mod, "hybrid_retriever", _SingleRetriever([doc]), raising=True)

    engine = RAGEngine()
    tokens: list[str] = []
    done_metrics: dict[str, object] = {}

    agen = engine.stream_chat(
        question="Which paper uses residual learning and shortcut connections to address degradation in very deep networks?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        request_id="source-identification-stream-test",
    )

    try:
        async for event in agen:
            if event.get("type") == "token":
                data = event.get("data") or {}
                tokens.append(str(data.get("content") or ""))
            if event.get("type") == "done":
                done_metrics = dict(((event.get("data") or {}).get("metrics") or {}))
                break
    finally:
        await agen.aclose()

    answer = "".join(tokens)
    assert answer == (
        'The paper is "Deep Residual Learning for Image Recognition" '
        "(source file: deep-residual-learning_1512.03385.pdf)."
    )
    assert done_metrics.get("source_identification_answer_used") is True
    assert done_metrics.get("confidence_score") == 1.0
