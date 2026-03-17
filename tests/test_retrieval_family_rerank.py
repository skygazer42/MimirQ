from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


class _RoutingRetriever:
    def __init__(self, *, by_query: dict[str, list[Document]]) -> None:
        self._by_query = {str(k): list(v) for k, v in (by_query or {}).items()}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, q: str):  # noqa: ANN001
        return list(self._by_query.get(str(q or "").strip(), []))


def _mk_doc(*, chunk_id: str, doc_id: str, chunk_index: int, family_key: str, score: float) -> Document:
    return Document(
        page_content=f"{chunk_id} content",
        id=chunk_id,
        metadata={
            "document_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_index": int(chunk_index),
            "hierarchy_family_key": family_key,
            "source": "t.md",
            "score": float(score),
        },
    )


def test_family_aggregation_frequency_promotes_multi_variant_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    # Keep deterministic and lightweight (no rewrite/decompose/KG).
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT", 1, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_MAX_CHARS", 200, raising=False)

    engine = RAGEngine()
    engine.models["fast"] = FakeListChatModel(responses=[json.dumps(["ALT1"])])
    monkeypatch.setattr(orch_mod, "get_rag_engine", lambda: engine, raising=True)

    # Family A appears in both main and mq; Family B appears only in main.
    docs_by_query = {
        "BASE": [
            _mk_doc(chunk_id="b:0", doc_id="doc-b", chunk_index=0, family_key="fam-b", score=0.99),
            _mk_doc(chunk_id="a:0", doc_id="doc-a", chunk_index=0, family_key="fam-a", score=0.80),
        ],
        "ALT1": [
            _mk_doc(chunk_id="a:1", doc_id="doc-a", chunk_index=1, family_key="fam-a", score=0.10),
        ],
    }
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _RoutingRetriever(by_query=docs_by_query), raising=True)

    state = {
        "question": "BASE",
        "history": [],
        "tenant_id": str(uuid.uuid4()),
        "account_id": "u",
        "dataset_id": None,
        "document_ids": [str(uuid.uuid4())],
        "top_k": 3,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "retrieval_profile": None,
        "enable_hierarchy_recall": True,
        "hierarchy_family_collapse": True,
        "hierarchy_family_aggregation": "frequency",
        "metrics": {},
    }

    out = orch_mod.run_retrieval(dict(state))
    docs = out.get("docs") or []
    assert [d.id for d in docs[:2]] == ["a:0", "a:1"]

