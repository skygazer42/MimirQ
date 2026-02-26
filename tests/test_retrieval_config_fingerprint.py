from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_emits_retrieval_config_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Deterministic: disable optional/LLM-dependent transforms.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Keep channel toggles stable for hashing.
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_RERANKER", False, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False, raising=False)

    # Avoid KG work.
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion affecting config signals.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    retriever = _FakeRetriever(
        docs=[
            Document(
                page_content="hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "t.md",
                    "score": 0.9,
                },
            )
        ]
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    base_state = {
        "question": "q1",
        "history": [],
        "tenant_id": str(uuid.uuid4()),
        "account_id": "u",
        "dataset_id": None,
        "document_ids": [str(doc_id)],
        "top_k": 5,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "alpha": 0.6,
        "metrics": {},
    }

    out1 = orch_mod.run_retrieval(dict(base_state))
    trace1 = out1.get("retrieval_trace")
    assert isinstance(trace1, dict)

    fp1 = trace1.get("retrieval_config")
    assert isinstance(fp1, dict)
    assert fp1.get("schema") == "mimirq.retrieval_config.v1"
    assert isinstance(fp1.get("hash"), str) and len(fp1.get("hash") or "") >= 16

    cfg1 = fp1.get("config")
    assert isinstance(cfg1, dict)
    assert cfg1.get("top_k") == 5
    assert cfg1.get("retrieval_mode") == "vector"
    assert "question" not in cfg1
    assert "document_ids" not in cfg1

    # Fingerprint must be stable across different question text when config is unchanged.
    out2 = orch_mod.run_retrieval({**base_state, "question": "q2"})
    fp2 = (out2.get("retrieval_trace") or {}).get("retrieval_config")
    assert isinstance(fp2, dict)
    assert fp2.get("hash") == fp1.get("hash")

    # Fingerprint must change when retrieval config changes.
    out3 = orch_mod.run_retrieval({**base_state, "top_k": 6})
    fp3 = (out3.get("retrieval_trace") or {}).get("retrieval_config")
    assert isinstance(fp3, dict)
    assert fp3.get("hash") != fp1.get("hash")

    # Fingerprint must change when a candidate-generation channel toggle changes.
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    out4 = orch_mod.run_retrieval(dict(base_state))
    fp4 = (out4.get("retrieval_trace") or {}).get("retrieval_config")
    assert isinstance(fp4, dict)
    assert fp4.get("hash") != fp1.get("hash")

    # Convenience: surface hash in metrics as well.
    metrics1 = out1.get("metrics") or {}
    assert isinstance(metrics1, dict)
    assert metrics1.get("retrieval_config_hash") == fp1.get("hash")
