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


def test_orchestrator_emits_citation_coverage_proxy_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Deterministic: disable any LLM-dependent query transforms.
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

    # Avoid dict expansion interfering with trace/metrics.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    doc_id_1 = uuid.uuid4()
    doc_id_2 = uuid.uuid4()
    chunk_1 = uuid.uuid4()
    chunk_2 = uuid.uuid4()
    chunk_3 = uuid.uuid4()

    retriever = _FakeRetriever(
        docs=[
            Document(
                page_content="hit 1",
                id=str(chunk_1),
                metadata={
                    "document_id": str(doc_id_1),
                    "chunk_id": str(chunk_1),
                    "chunk_index": 0,
                    "doc_pipeline_key": "pipe_a",
                    "retrieval_role": "vector",
                    "source": "a.md",
                    "score": 0.9,
                },
            ),
            Document(
                page_content="hit 2",
                id=str(chunk_2),
                metadata={
                    "document_id": str(doc_id_1),
                    "chunk_id": str(chunk_2),
                    "chunk_index": 1,
                    "doc_pipeline_key": "pipe_a",
                    "retrieval_role": "vector",
                    "source": "a.md",
                    "score": 0.8,
                },
            ),
            Document(
                page_content="hit 3",
                id=str(chunk_3),
                metadata={
                    "document_id": str(doc_id_2),
                    "chunk_id": str(chunk_3),
                    "chunk_index": 0,
                    "doc_pipeline_key": "pipe_b",
                    "retrieval_role": "kg",
                    "source": "b.md",
                    "score": 0.7,
                },
            ),
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
            "document_ids": [str(doc_id_1), str(doc_id_2)],
            "top_k": 5,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    metrics = out.get("metrics") or {}
    cov = metrics.get("citation_coverage") or {}
    assert cov.get("citations_total") == 3
    assert cov.get("distinct_documents") == 2
    assert cov.get("distinct_pipeline_keys") == 2
    assert cov.get("distinct_roles") == 2
    assert cov.get("top_doc_share") == pytest.approx(0.667)

