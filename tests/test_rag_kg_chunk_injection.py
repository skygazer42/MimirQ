from __future__ import annotations

import uuid

from langchain_core.documents import Document

from tests.helpers.async_utils import yield_control


class _FakeChunk:
    def __init__(
        self,
        *,
        chunk_id: uuid.UUID,
        document_id: uuid.UUID,
        chunk_index: int,
        content: str,
        score: float,
    ) -> None:
        self.id = chunk_id
        self.document_id = document_id
        self.chunk_index = int(chunk_index)
        self.content = content
        self.page_number = 1
        self.start_char = 0
        self.end_char = len(content)
        self.doc_metadata = {"source": "kg.md", "score": score}


class _FakeRetriever:
    def __init__(self, *, docs: list[Document] | None = None) -> None:
        self._docs = list(docs or [])
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_kg_chunk_injection_injects_and_caps(monkeypatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Deterministic: no extra LLM features.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Enable KG chunk injection (the feature under test).
    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 2, raising=False)

    # Keep dict expansion from adding noise to query execution (not needed for this test).
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(expand_mod, "generate_dictionary_expansions", lambda **_k: ([], {"enabled": False, "used": False}), raising=True)

    # No retrieval hits from the normal retriever.
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[]), raising=True)

    kg_chunk_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        await yield_control()
        assert query
        assert tenant_id is not None
        assert document_ids
        return {
            "events": [
                {"chunk_id": str(kg_chunk_ids[0]), "score": 0.9},
                {"chunk_id": str(kg_chunk_ids[1]), "score": 0.8},
                {"chunk_id": str(kg_chunk_ids[2]), "score": 0.7},
            ],
            "entities": [],
            "stats": {"ok": True},
        }

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    doc_id = uuid.uuid4()

    def _fake_fetch_chunks(*, db, tenant_id, account_id, dataset_id, document_ids, chunk_ids):  # noqa: ANN001
        # Return rows for all chunks even though injection should cap to 2 by event order.
        return [
            _FakeChunk(chunk_id=kg_chunk_ids[0], document_id=doc_id, chunk_index=1, content="c0", score=0.9),
            _FakeChunk(chunk_id=kg_chunk_ids[1], document_id=doc_id, chunk_index=2, content="c1", score=0.8),
            _FakeChunk(chunk_id=kg_chunk_ids[2], document_id=doc_id, chunk_index=3, content="c2", score=0.7),
        ]

    monkeypatch.setattr(orch_mod, "_fetch_document_chunks_for_kg_injection", _fake_fetch_chunks, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": uuid.uuid4(),
            "account_id": "u",
            "document_ids": [doc_id],
            "top_k": 3,
            "retrieval_mode": "vector",
            "metrics": {},
            "db": object(),  # not used by fake fetch, but required by signature
        }
    )

    citations = out.get("citations") or []
    assert len(citations) == 2
    assert [c.get("chunk_id") for c in citations] == [str(kg_chunk_ids[0]), str(kg_chunk_ids[1])]
    assert all(c.get("retrieval_role") == "kg" for c in citations)

    metrics = out.get("metrics") or {}
    assert metrics.get("kg_chunks_injected") == 2


def test_orchestrator_kg_chunk_injection_uses_multi_dataset_scope(monkeypatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 2, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(expand_mod, "generate_dictionary_expansions", lambda **_k: ([], {"enabled": False, "used": False}), raising=True)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[]), raising=True)

    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    kg_calls: list[dict[str, object]] = []

    async def _fake_kg_search(
        *,
        query,
        tenant_id=None,
        document_ids=None,
        dataset_id=None,
        dataset_ids=None,
        account_id=None,
    ):  # noqa: ANN001
        await yield_control()
        kg_calls.append(
            {
                "query": query,
                "tenant_id": tenant_id,
                "document_ids": document_ids,
                "dataset_id": dataset_id,
                "dataset_ids": dataset_ids,
                "account_id": account_id,
            }
        )
        return {"events": [{"chunk_id": str(chunk_id), "score": 0.92}], "entities": []}

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    def _fake_fetch_chunks(**kwargs):  # noqa: ANN003
        assert kwargs["dataset_id"] is None
        assert kwargs["dataset_ids"] == [dataset_a, dataset_b]
        assert kwargs["document_ids"] == []
        return [_FakeChunk(chunk_id=chunk_id, document_id=doc_id, chunk_index=1, content="kg", score=0.92)]

    monkeypatch.setattr(orch_mod, "_fetch_document_chunks_for_kg_injection", _fake_fetch_chunks, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": uuid.uuid4(),
            "account_id": "u",
            "dataset_ids": [dataset_a, dataset_b],
            "top_k": 3,
            "retrieval_mode": "vector",
            "metrics": {},
            "db": object(),
        }
    )

    assert kg_calls
    assert kg_calls[0]["document_ids"] is None
    assert kg_calls[0]["dataset_id"] is None
    assert kg_calls[0]["dataset_ids"] == [dataset_a, dataset_b]
    citations = out.get("citations") or []
    assert [c.get("chunk_id") for c in citations] == [str(chunk_id)]
    assert citations[0].get("retrieval_role") == "kg"


def test_orchestrator_kg_chunk_injection_dedupes_existing_docs(monkeypatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 5, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(expand_mod, "generate_dictionary_expansions", lambda **_k: ([], {"enabled": False, "used": False}), raising=True)

    doc_id = uuid.uuid4()
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()

    # Retriever already returned cid1.
    retriever_docs = [
        Document(
            page_content="retriever hit",
            metadata={"document_id": str(doc_id), "chunk_id": str(cid1), "chunk_index": 1, "source": "retriever.md"},
            id=str(cid1),
        )
    ]
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=retriever_docs), raising=True)

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        await yield_control()
        return {"events": [{"chunk_id": str(cid1), "score": 0.9}, {"chunk_id": str(cid2), "score": 0.8}], "entities": []}

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    def _fake_fetch_chunks(*, db, tenant_id, account_id, dataset_id, document_ids, chunk_ids):  # noqa: ANN001
        return [
            _FakeChunk(chunk_id=cid1, document_id=doc_id, chunk_index=1, content="c1", score=0.9),
            _FakeChunk(chunk_id=cid2, document_id=doc_id, chunk_index=2, content="c2", score=0.8),
        ]

    monkeypatch.setattr(orch_mod, "_fetch_document_chunks_for_kg_injection", _fake_fetch_chunks, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": uuid.uuid4(),
            "account_id": "u",
            "document_ids": [doc_id],
            "top_k": 3,
            "retrieval_mode": "vector",
            "metrics": {},
            "db": object(),
        }
    )

    citations = out.get("citations") or []
    # cid1 should appear only once, but the main retriever version must keep its
    # score/role. KG should enrich duplicates instead of downgrading them.
    assert [c.get("chunk_id") for c in citations] == [str(cid1), str(cid2)]
    assert citations[0].get("retrieval_role") == "main"
    assert citations[0].get("kg_pagerank") == 0.9
    assert citations[1].get("retrieval_role") == "kg"


def test_orchestrator_kg_chunk_boost_promotes_injected_candidate_when_enabled(monkeypatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 5, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_BOOST_ENABLED", False, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(expand_mod, "generate_dictionary_expansions", lambda **_k: ([], {"enabled": False, "used": False}), raising=True)

    doc_id = uuid.uuid4()
    main_chunk = uuid.uuid4()
    kg_chunk = uuid.uuid4()
    main_doc = Document(
        page_content="main",
        metadata={
            "document_id": str(doc_id),
            "chunk_id": str(main_chunk),
            "chunk_index": 0,
            "source": "main.md",
            "score": 0.2,
            "retrieval_score": 0.2,
        },
        id=str(main_chunk),
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[main_doc]), raising=True)

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        await yield_control()
        return {"events": [{"chunk_id": str(kg_chunk), "score": 0.95}], "entities": []}

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    def _fake_fetch_chunks(*, db, tenant_id, account_id, dataset_id, document_ids, chunk_ids):  # noqa: ANN001
        return [_FakeChunk(chunk_id=kg_chunk, document_id=doc_id, chunk_index=1, content="kg", score=0.95)]

    monkeypatch.setattr(orch_mod, "_fetch_document_chunks_for_kg_injection", _fake_fetch_chunks, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": uuid.uuid4(),
            "account_id": "u",
            "document_ids": [doc_id],
            "top_k": 2,
            "retrieval_mode": "vector",
            "metrics": {},
            "db": object(),
            "enable_kg_chunk_boost": True,
            "kg_chunk_boost_weight": 1.0,
            "kg_chunk_boost_max_promoted": 1,
        }
    )

    citations = out.get("citations") or []
    assert [c.get("chunk_id") for c in citations] == [str(kg_chunk), str(main_chunk)]
    assert citations[0].get("kg_boost_applied") is True
    metrics = out.get("metrics") or {}
    assert metrics.get("kg_chunk_boost_enabled") is True
    assert metrics.get("kg_chunk_boost_promoted") == 1
    assert metrics.get("kg_chunk_boost_top_changed") is True


def test_orchestrator_kg_chunk_injection_disabled_does_not_call_kg(monkeypatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(expand_mod, "generate_dictionary_expansions", lambda **_k: ([], {"enabled": False, "used": False}), raising=True)

    doc_id = uuid.uuid4()
    cid = uuid.uuid4()
    monkeypatch.setattr(
        orch_mod,
        "hybrid_retriever",
        _FakeRetriever(
            docs=[
                Document(
                    page_content="retriever hit",
                    metadata={"document_id": str(doc_id), "chunk_id": str(cid), "source": "retriever.md"},
                    id=str(cid),
                )
            ]
        ),
        raising=True,
    )

    kg_calls = {"n": 0}

    async def _fake_kg_search(*_a, **_k):  # noqa: ANN001
        await yield_control()
        kg_calls["n"] += 1
        return {"events": []}

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    fetch_calls = {"n": 0}

    def _fake_fetch_chunks(*_a, **_k):  # noqa: ANN001
        fetch_calls["n"] += 1
        return []

    monkeypatch.setattr(orch_mod, "_fetch_document_chunks_for_kg_injection", _fake_fetch_chunks, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": uuid.uuid4(),
            "account_id": "u",
            "document_ids": [doc_id],
            "top_k": 3,
            "retrieval_mode": "vector",
            "metrics": {},
            "db": object(),
        }
    )

    assert kg_calls["n"] == 0
    assert fetch_calls["n"] == 0

    citations = out.get("citations") or []
    assert len(citations) == 1
    assert citations[0].get("retrieval_role") == "main"
