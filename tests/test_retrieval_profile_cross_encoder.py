from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _CapturingRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_update: dict = {}
        self._last_debug_metrics: dict = {}

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN001
        self._last_update = dict(update or {})
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_hybrid_ce_profile_degrades_to_hybrid_without_reranker_runtime(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.retrieval.orchestrator as orch_mod
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
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_INTENT_ROUTER_ENABLED", False, raising=False)

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    retriever = _CapturingRetriever(
        docs=[
            Document(
                page_content="cross encoder baseline hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "doc.md",
                    "score": 0.8,
                },
            )
        ]
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    state = {
        "question": "what changed",
        "history": [],
        "tenant_id": str(uuid.uuid4()),
        "account_id": "acct",
        "document_ids": [str(doc_id)],
        "top_k": 5,
        "score_threshold": 0.7,
        "retrieval_mode": "keyword",
        "enable_reranker": False,
        "reranker_provider": "llm",
        "reranker_top_n": 3,
        "enable_weight_rerank": True,
        "retrieval_profile": "hybrid_ce",
        "metrics": {},
    }

    out = orch_mod.run_retrieval(dict(state))

    assert retriever._last_update["retrieval_mode"] == "hybrid"
    assert retriever._last_update["enable_reranker"] is False
    assert retriever._last_update["reranker_provider"] == "none"
    assert retriever._last_update["enable_weight_rerank"] is False
    assert int(retriever._last_update["k"]) >= 20
    assert int(retriever._last_update["reranker_top_n"]) == 3
    assert float(retriever._last_update["score_threshold"]) == pytest.approx(0.0)

    metrics = out.get("metrics") or {}
    assert metrics.get("retrieval_profile") == "hybrid_ce"
    fp = (out.get("retrieval_trace") or {}).get("retrieval_config") or {}
    cfg = fp.get("config") or {}
    assert cfg.get("retrieval_profile") == "hybrid_ce"
    assert cfg.get("reranker_provider") == "none"
    assert cfg.get("reranker_tier") == "disabled"


def test_orchestrator_hybrid_ce_profile_wires_cross_encoder_runtime_when_enabled(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.retrieval.orchestrator as orch_mod
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
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_INTENT_ROUTER_ENABLED", False, raising=False)

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    retriever = _CapturingRetriever(
        docs=[
            Document(
                page_content="cross encoder baseline hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "doc.md",
                    "score": 0.8,
                },
            )
        ]
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    state = {
        "question": "what changed",
        "history": [],
        "tenant_id": str(uuid.uuid4()),
        "account_id": "acct",
        "document_ids": [str(doc_id)],
        "top_k": 5,
        "score_threshold": 0.7,
        "retrieval_mode": "keyword",
        "enable_reranker": True,
        "reranker_provider": "llm",
        "reranker_top_n": 3,
        "enable_weight_rerank": True,
        "retrieval_profile": "hybrid_ce",
        "metrics": {},
    }

    out = orch_mod.run_retrieval(dict(state))

    assert retriever._last_update["retrieval_mode"] == "hybrid"
    assert retriever._last_update["enable_reranker"] is True
    assert retriever._last_update["reranker_provider"] == "cross_encoder"
    assert retriever._last_update["enable_weight_rerank"] is False
    assert int(retriever._last_update["k"]) >= 20
    assert int(retriever._last_update["reranker_top_n"]) >= 20
    assert float(retriever._last_update["score_threshold"]) == pytest.approx(0.0)

    metrics = out.get("metrics") or {}
    assert metrics.get("retrieval_profile") == "hybrid_ce"
    fp = (out.get("retrieval_trace") or {}).get("retrieval_config") or {}
    cfg = fp.get("config") or {}
    assert cfg.get("retrieval_profile") == "hybrid_ce"
    assert cfg.get("reranker_provider") == "cross_encoder"
    assert cfg.get("reranker_tier") == "prod"
