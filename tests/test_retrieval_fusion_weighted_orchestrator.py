from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _CapturingRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self.last_update: dict | None = None
        self._last_debug_metrics: dict = {}

    def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
        update = kwargs.get("update")
        if isinstance(update, dict):
            self.last_update = dict(update)
        else:
            self.last_update = None
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_passes_weighted_fusion_weights_into_retriever(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Deterministic: disable any LLM-dependent transforms.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Avoid KG work.
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion interfering with trace shape.
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

    retriever = _CapturingRetriever(
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

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(doc_id)],
            "top_k": 5,
            "retrieval_mode": "vector",
            "fusion_strategy": "weighted",
            "fusion_weights": {"vector": 0.2, "bm25": 0.8},
            "metrics": {},
        }
    )

    assert retriever.last_update is not None
    assert retriever.last_update.get("fusion_strategy") == "weighted"
    assert retriever.last_update.get("fusion_weights") == {"vector": 0.2, "bm25": 0.8}

    fp = (out.get("retrieval_trace") or {}).get("retrieval_config") or {}
    cfg = fp.get("config") or {}
    assert cfg.get("fusion_strategy") == "weighted"
    assert cfg.get("fusion_weights") == {"vector": 0.2, "bm25": 0.8}

