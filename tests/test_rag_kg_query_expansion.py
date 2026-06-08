from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document

from tests.helpers.async_utils import yield_control


class _FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, q: str):  # noqa: ANN001
        self.calls.append(str(q))
        if "ACME" in str(q):
            doc_id = uuid.uuid4()
            return [
                Document(
                    page_content="hit from kg query expansion",
                    metadata={
                        "document_id": str(doc_id),
                        "chunk_id": str(uuid.uuid4()),
                        "source": "acme.md",
                        "score": 0.9,
                    },
                )
            ]
        return []


def test_rag_engine_query_variant_role_overrides_retriever_default() -> None:
    from app.rag.engine import RAGEngine

    doc = Document(page_content="hit", metadata={"retrieval_role": "main", "chunk_id": str(uuid.uuid4())})

    out = RAGEngine._annotate_docs_with_role([doc], "kgq")

    assert out[0].metadata["retrieval_role"] == "kgq"


@pytest.mark.asyncio
async def test_rag_engine_uses_kg_entity_query_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    # Deterministic, no-op LLM.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    # Enable KG + query expansion.
    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Avoid dict expansion interfering with query-count assertions.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    # Avoid TAG work.
    import app.services.chat_tag_service as tag_mod

    monkeypatch.setattr(
        tag_mod,
        "build_chat_tag_context_docs",
        lambda *_a, **_k: ([], {"enabled": False, "used": False, "reason": "not_run", "returned": 0}),
        raising=True,
    )

    retriever = _FakeRetriever()
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    kg_calls = {"n": 0}

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        await yield_control()
        kg_calls["n"] += 1
        assert query
        assert tenant_id is not None
        assert document_ids
        return {
            "entities": [
                {"entity_id": str(uuid.uuid4()), "name": "ACME", "type": "Organization", "weight": 0.9},
            ],
            "events": [],
            "stats": {"ok": True},
        }

    monkeypatch.setattr(engine_mod, "kg_search", _fake_kg_search, raising=True)

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="q",
        history=None,
        conversation_id=None,
        document_ids=[doc_id],
        tenant_id=tenant_id,
        account_id="u",
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=object(),
    )

    citations = None
    done_metrics = None
    async for item in agen:
        if item.get("type") == "citations":
            citations = item.get("data")
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert kg_calls["n"] == 1
    assert "q" in retriever.calls
    assert any("ACME" in c for c in retriever.calls)

    assert isinstance(citations, list)
    assert len(citations) == 1
    assert citations[0].get("retrieval_role") == "kgq"
    assert done_metrics.get("kg_query_expansion_used") is True


@pytest.mark.asyncio
async def test_rag_engine_kg_query_expansion_excludes_skill_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES", "Skill,SkillTag,SkillCategory", raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Avoid dict expansion interfering with query-count assertions.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    # Avoid TAG work.
    import app.services.chat_tag_service as tag_mod

    monkeypatch.setattr(
        tag_mod,
        "build_chat_tag_context_docs",
        lambda *_a, **_k: ([], {"enabled": False, "used": False, "reason": "not_run", "returned": 0}),
        raising=True,
    )

    retriever = _FakeRetriever()
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        await yield_control()
        assert query
        assert tenant_id is not None
        assert document_ids
        return {
            "entities": [
                # This should be ignored by query expansion since it's Skill-like.
                {"entity_id": str(uuid.uuid4()), "name": "ACME", "type": "Skill", "weight": 0.9},
            ],
            "events": [],
            "stats": {"ok": True},
        }

    monkeypatch.setattr(engine_mod, "kg_search", _fake_kg_search, raising=True)

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="q",
        history=None,
        conversation_id=None,
        document_ids=[doc_id],
        tenant_id=tenant_id,
        account_id="u",
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=object(),
    )

    done_metrics = None
    async for item in agen:
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert "q" in retriever.calls
    assert not any("ACME" in c for c in retriever.calls)
    assert done_metrics.get("kg_query_expansion_used") is False


def test_langgraph_retrieve_node_uses_kg_entity_query_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", True, raising=False)

    # Avoid dict expansion.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    retriever = _FakeRetriever()
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    kg_calls = {"n": 0}

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        await yield_control()
        kg_calls["n"] += 1
        assert query
        assert tenant_id is not None
        assert dataset_id is not None
        assert account_id
        return {
            "entities": [
                {"entity_id": str(uuid.uuid4()), "name": "ACME", "type": "Organization", "weight": 0.9},
            ],
            "events": [],
            "stats": {"ok": True},
        }

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    out = lg_mod._retrieve_node(
        {
            "question": "q",
            "history": [],
            "tenant_id": uuid.uuid4(),
            "account_id": "u",
            "dataset_id": uuid.uuid4(),
            "document_ids": [],
            "metrics": {},
        }
    )

    assert kg_calls["n"] == 1
    assert "q" in retriever.calls
    assert any("ACME" in c for c in retriever.calls)

    metrics = out.get("metrics") or {}
    assert metrics.get("kg_query_expansion_used") is True

    qd = out.get("query_debug") or {}
    expansions = qd.get("expansions") or []
    assert any(e.get("kind") == "kgq" for e in expansions if isinstance(e, dict))
