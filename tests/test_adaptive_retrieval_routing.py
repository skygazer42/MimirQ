
import json
import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


class _CapturingRetriever:
    def __init__(self, *, main_docs: list[Document], mq_docs: dict[str, list[Document]]) -> None:
        self._main_docs = list(main_docs)
        self._mq_docs = {str(k): list(v) for k, v in (mq_docs or {}).items()}
        self._last_debug_metrics: dict = {}
        self._model_copy_updates: list[dict[str, object]] = []

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN001
        self._model_copy_updates.append(dict(update or {}))
        return self

    def invoke(self, q: str):  # noqa: ANN001
        q = (q or "").strip()
        if q == "BASE":
            return list(self._main_docs)
        return list(self._mq_docs.get(q, []))


def _mk_doc(*, doc_id: str, chunk_index: int) -> Document:
    chunk_id = f"{doc_id}:{chunk_index}"
    return Document(
        page_content=f"{chunk_id} content",
        id=chunk_id,
        metadata={
            "document_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_index": int(chunk_index),
            "source": "t.md",
            "score": 1.0,
        },
    )


def test_engine_routes_retrieval_params_by_complexity_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_ROUTING_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_SIMPLE_THRESHOLD", 80.0, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_SIMPLE_TOP_K", 7, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_THRESHOLD", 200.0, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_TOP_K", 33, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_MQ_COUNT", 4, raising=False)

    engine = RAGEngine()

    assert engine._route_retrieval_params(40.0) == {
        "top_k": 7,
        "enable_multi_query": False,
    }
    assert engine._route_retrieval_params(150.0) == {}
    assert engine._route_retrieval_params(250.0) == {
        "top_k": 33,
        "enable_multi_query": True,
        "multi_query_count": 4,
        "retrieval_profile": "recall50",
    }


@pytest.mark.asyncio
async def test_engine_applies_adaptive_retrieval_overrides_to_streaming_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_ROUTING_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_SIMPLE_THRESHOLD", 80.0, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_SIMPLE_TOP_K", 6, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_THRESHOLD", 200.0, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_TOP_K", 9, raising=False)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_MQ_COUNT", 2, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_MAX_CHARS", 400, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    engine = RAGEngine()
    engine.models["fast"] = FakeListChatModel(responses=[json.dumps(["ALT-1", "ALT-2"])])
    fake_gen = FakeListChatModel(responses=["ok"])
    monkeypatch.setattr(engine, "_select_llm", lambda *_a, **_k: (fake_gen, "fake", "test"), raising=True)

    main_docs = [_mk_doc(doc_id="z-main", chunk_index=i) for i in range(0, 6)]
    mq_docs = {"ALT-1": [_mk_doc(doc_id="mq-doc", chunk_index=0)]}
    fake_retriever = _CapturingRetriever(main_docs=main_docs, mq_docs=mq_docs)
    monkeypatch.setattr(engine_mod, "hybrid_retriever", fake_retriever, raising=True)

    complex_question = "Analyze and compare BASE versus ALT step-by-step with code examples and tradeoffs."

    agen = engine.stream_chat(
        question=complex_question,
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=4,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="adaptive-routing-test",
    )

    done_metrics = None
    try:
        async for ev in agen:
            if ev.get("type") == "done":
                done_metrics = (ev.get("data") or {}).get("metrics") or {}
                break
    finally:
        await agen.aclose()

    base_update = next(update for update in fake_retriever._model_copy_updates if "k" in update)
    assert base_update["k"] == 9
    assert base_update["retrieval_profile"] == "recall50"

    assert isinstance(done_metrics, dict)
    assert done_metrics.get("adaptive_retrieval_used") is True
    assert done_metrics.get("adaptive_retrieval_overrides") == {
        "top_k": 9,
        "enable_multi_query": True,
        "multi_query_count": 2,
        "retrieval_profile": "recall50",
    }
    assert done_metrics.get("multi_query_used") is True
