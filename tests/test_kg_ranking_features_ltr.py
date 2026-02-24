from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.reranker.ltr import LTRFeatureSpec, train_ltr_xgboost_model


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
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_kg_ranking_features_help_ltr_rerank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    # Deterministic: no extra LLM features.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)

    # Enable KG injection (to produce retrieval_role="kg" candidates).
    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 5, raising=False)

    # Enable post-fusion rerank with LTR (v2 spec includes KG features).
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "ltr", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 10, raising=False)
    monkeypatch.setattr(settings, "LTR_FEATURE_SPEC_VERSION", 2, raising=False)

    # Train a tiny model that prefers kg_evidence_anchored candidates.
    spec = LTRFeatureSpec.v2()
    rows = []
    for anchored, label in ((1.0, 1), (0.0, 0)):
        feats = {k: 0.0 for k in spec.feature_names}
        feats["kg_evidence_anchored"] = float(anchored)
        rows.append({"features": feats, "label": int(label)})

    model_path = tmp_path / "ltr.json"
    model_path.write_bytes(train_ltr_xgboost_model(training_rows=rows, spec=spec, num_boost_round=5, seed=7))
    monkeypatch.setattr(settings, "LTR_MODEL_PATH", str(model_path), raising=False)

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    main_chunk = uuid.uuid4()
    kg_chunk = uuid.uuid4()

    # Main retriever returns a high-score hit that should lose to KG after LTR rerank.
    main_doc = Document(
        page_content="main",
        id=str(main_chunk),
        metadata={
            "document_id": str(doc_id),
            "chunk_id": str(main_chunk),
            "chunk_index": 0,
            "source": "main.md",
            "score": 0.9,
            "vector_score": 0.9,
        },
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[main_doc]), raising=True)

    async def _fake_kg_search(*, query, tenant_id=None, document_ids=None, dataset_id=None, account_id=None):  # noqa: ANN001
        assert query
        assert tenant_id is not None
        assert document_ids
        return {"events": [{"chunk_id": str(kg_chunk), "score": 0.1}], "entities": [], "stats": {"ok": True}}

    monkeypatch.setattr(orch_mod, "kg_search", _fake_kg_search, raising=True)

    def _fake_fetch_chunks(*, db, tenant_id, account_id, dataset_id, document_ids, chunk_ids):  # noqa: ANN001
        return [_FakeChunk(chunk_id=kg_chunk, document_id=doc_id, chunk_index=1, content="kg", score=0.1)]

    monkeypatch.setattr(orch_mod, "_fetch_document_chunks_for_kg_injection", _fake_fetch_chunks, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": tenant_id,
            "account_id": "u",
            "document_ids": [doc_id],
            "top_k": 2,
            "retrieval_mode": "vector",
            "metrics": {},
            "db": object(),
        }
    )

    citations = out.get("citations") or []
    assert [c.get("chunk_id") for c in citations][:2] == [str(kg_chunk), str(main_chunk)]
    assert citations[0].get("kg_evidence_anchored") is True

