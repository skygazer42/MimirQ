from __future__ import annotations

import asyncio
import uuid

import pytest
from langchain_core.documents import Document


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
        self.doc_metadata = {"source": "kg.md", "score": float(score)}


class _FakeRetriever:
    def __init__(self, *, docs: list[Document] | None = None) -> None:
        self._docs = list(docs or [])
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_propagates_kg_ranking_features_from_kg_search(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Deterministic: no extra LLM features.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False, raising=False)

    # Enable KG injection.
    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 1, raising=False)

    # Avoid dict expansion noise.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    # Base retriever returns nothing; only KG injection contributes.
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[]), raising=True)

    doc_id = uuid.uuid4()
    kg_chunk = uuid.uuid4()

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        assert query
        assert tenant_id is not None
        assert document_ids
        return {
            "events": [
                {
                    "chunk_id": str(kg_chunk),
                    "score": 0.6,
                    "kg_path_length": 3,
                    "kg_shared_events": 2,
                    "kg_evidence_anchored": False,
                    "kg_path": [{"entity_id": "e1", "type": "Skill"}],
                    "kg_path_provenance": {
                        "schema": "mimirq.kg_path_provenance.v1",
                        "kind": "entity_event_entity",
                        "hops": 2,
                        "nodes": [
                            {"kind": "entity", "entity_id": "e1", "type": "Skill"},
                            {"kind": "event", "event_id": "ev1", "document_id": str(doc_id), "chunk_id": str(kg_chunk)},
                            {"kind": "entity", "entity_id": "e2", "type": "Tool"},
                        ],
                        "edges": [
                            {"kind": "event_entity", "entity_id": "e1", "event_id": "ev1", "document_id": str(doc_id), "chunk_id": str(kg_chunk)},
                            {"kind": "event_entity", "entity_id": "e2", "event_id": "ev1", "document_id": str(doc_id), "chunk_id": str(kg_chunk)},
                        ],
                    },
                }
            ],
            "entities": [],
            "stats": {"ok": True},
        }

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    def _fake_fetch_chunks(*, db, tenant_id, account_id, dataset_id, document_ids, chunk_ids):  # noqa: ANN001
        return [_FakeChunk(chunk_id=kg_chunk, document_id=doc_id, chunk_index=1, content="kg", score=0.6)]

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
    assert len(citations) == 1
    c0 = citations[0] or {}

    assert c0.get("retrieval_role") == "kg"
    assert c0.get("chunk_id") == str(kg_chunk)

    # Propagated ranking signals (stable, low-cardinality).
    assert c0.get("kg_path_length") == 3
    assert c0.get("kg_shared_events") == 2
    assert c0.get("kg_evidence_anchored") is False

    # Buckets derived from the KG score when not explicitly provided.
    assert c0.get("kg_pagerank") == pytest.approx(0.6)
    assert c0.get("kg_edge_conf_low") == pytest.approx(0.0)
    assert c0.get("kg_edge_conf_mid") == pytest.approx(1.0)
    assert c0.get("kg_edge_conf_high") == pytest.approx(0.0)

    # Provenance payload should be propagated to citations (PII-safe, bounded).
    assert c0.get("kg_path") == [{"entity_id": "e1", "type": "Skill"}]
    prov = c0.get("kg_path_provenance")
    assert isinstance(prov, dict)
    assert prov.get("schema") == "mimirq.kg_path_provenance.v1"
    assert prov.get("kind") == "entity_event_entity"
