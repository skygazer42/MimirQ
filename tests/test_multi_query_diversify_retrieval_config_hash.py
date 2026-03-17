from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


class _RoutingRetriever:
    def __init__(self, *, main_docs: list[Document], mq_docs: dict[str, list[Document]]) -> None:
        self._main_docs = list(main_docs)
        self._mq_docs = {str(k): list(v) for k, v in (mq_docs or {}).items()}
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, q: str):  # noqa: ANN001
        q = (q or "").strip()
        if q == "BASE":
            return list(self._main_docs)
        return list(self._mq_docs.get(q, []))


def _mk_doc(*, doc_id: str, chunk_index: int, family_key: str | None = None) -> Document:
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
            "hierarchy_family_key": family_key,
        },
    )


def test_orchestrator_retrieval_config_hash_includes_multi_query_diversify_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    # Keep deterministic.
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
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT", 2, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_MAX_CHARS", 200, raising=False)

    engine = RAGEngine()
    mq_llm = FakeListChatModel(responses=[json.dumps(["ALT1", "ALT2"])])
    engine.models["fast"] = mq_llm
    monkeypatch.setattr(orch_mod, "get_rag_engine", lambda: engine, raising=True)

    main_docs = [_mk_doc(doc_id="z-main", chunk_index=i) for i in range(0, 4)]
    mq_docs = {
        "ALT1": [_mk_doc(doc_id="a-alt1", chunk_index=0)],
        "ALT2": [_mk_doc(doc_id="a-alt2", chunk_index=0)],
    }
    retriever = _RoutingRetriever(main_docs=main_docs, mq_docs=mq_docs)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    base_state = {
        "question": "BASE",
        "history": [],
        "tenant_id": str(uuid.uuid4()),
        "account_id": "u",
        "dataset_id": None,
        "document_ids": [str(uuid.uuid4())],
        "top_k": 4,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "metrics": {},
    }

    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 0, raising=False)
    out1 = orch_mod.run_retrieval(dict(base_state))
    h1 = (out1.get("metrics") or {}).get("retrieval_config_hash")
    assert isinstance(h1, str) and len(h1) >= 16

    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 1, raising=False)
    out2 = orch_mod.run_retrieval(dict(base_state))
    h2 = (out2.get("metrics") or {}).get("retrieval_config_hash")
    assert isinstance(h2, str) and len(h2) >= 16

    assert h2 != h1


def test_orchestrator_records_per_query_family_hits_before_fusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    # Keep deterministic.
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
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT", 2, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_MAX_CHARS", 200, raising=False)

    engine = RAGEngine()
    mq_llm = FakeListChatModel(responses=[json.dumps(["ALT1", "ALT2"])])
    engine.models["fast"] = mq_llm
    monkeypatch.setattr(orch_mod, "get_rag_engine", lambda: engine, raising=True)

    main_docs = [
        _mk_doc(doc_id="z-main", chunk_index=0, family_key="fam-a"),
        _mk_doc(doc_id="z-main", chunk_index=1, family_key="fam-b"),
    ]
    mq_docs = {
        "ALT1": [_mk_doc(doc_id="a-alt1", chunk_index=0, family_key="fam-a")],
        # Duplicate family hits within the same variant should be visible in the debug stats.
        "ALT2": [
            _mk_doc(doc_id="a-alt2", chunk_index=0, family_key="fam-a"),
            _mk_doc(doc_id="a-alt2", chunk_index=1, family_key="fam-a"),
        ],
    }
    retriever = _RoutingRetriever(main_docs=main_docs, mq_docs=mq_docs)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    base_state = {
        "question": "BASE",
        "history": [],
        "tenant_id": str(uuid.uuid4()),
        "account_id": "u",
        "dataset_id": None,
        "document_ids": [str(uuid.uuid4())],
        "top_k": 4,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "retrieval_profile": "hierarchy_recall20",
        "metrics": {},
    }

    out = orch_mod.run_retrieval(dict(base_state))
    metrics = out.get("metrics") or {}
    per_query = metrics.get("retrieval_per_query") or []
    assert isinstance(per_query, list) and per_query

    def _dbg(kind: str) -> dict:
        for it in per_query:
            if not isinstance(it, dict):
                continue
            if str(it.get("kind") or "").strip() == kind:
                dbg = it.get("retriever_debug") or {}
                assert isinstance(dbg, dict)
                return dbg
        raise AssertionError(f"missing per-query item for kind={kind}")

    dbg_main = _dbg("main")
    fam_main = dbg_main.get("hierarchy_family") or {}
    assert fam_main.get("docs") == 2
    assert fam_main.get("distinct_families") == 2
    assert fam_main.get("duplicate_docs") == 0

    mq_items = [it for it in per_query if isinstance(it, dict) and str(it.get("kind") or "") == "mq"]
    assert len(mq_items) == 2
    mq_fams = []
    for it in mq_items:
        dbg = it.get("retriever_debug") or {}
        assert isinstance(dbg, dict)
        fam = dbg.get("hierarchy_family") or {}
        assert isinstance(fam, dict)
        mq_fams.append(fam)

    assert max(int(x.get("docs") or 0) for x in mq_fams) == 2
    assert any(int(x.get("duplicate_docs") or 0) == 1 for x in mq_fams)
