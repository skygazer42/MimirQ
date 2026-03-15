from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.reranker.ltr import LTRFeatureSpec, train_ltr_xgboost_model


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_evidence_post_rerank_applies_ltr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    # Deterministic: no extra LLM features.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)

    # Enable post-rerank.
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "ltr", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 10, raising=False)

    # Train a tiny model that prefers higher vector_score.
    spec = LTRFeatureSpec.default()
    rows = []
    for score, label in ((0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)):
        feats = dict.fromkeys(spec.feature_names, 0.0)
        feats["vector_score"] = float(score)
        feats["role_main"] = 1.0
        rows.append({"features": feats, "label": int(label)})

    model_path = tmp_path / "ltr.json"
    model_path.write_bytes(
        train_ltr_xgboost_model(training_rows=rows, spec=spec, num_boost_round=5, seed=7)
    )
    monkeypatch.setattr(settings, "LTR_MODEL_PATH", str(model_path), raising=False)

    doc_id = "doc"
    # Retriever returns low-score first, high-score second.
    d1 = Document(
        page_content="low",
        id="a",
        metadata={"document_id": doc_id, "chunk_id": "a", "chunk_index": 0, "score": 0.1, "vector_score": 0.1, "source": "x"},
    )
    d2 = Document(
        page_content="high",
        id="b",
        metadata={"document_id": doc_id, "chunk_id": "b", "chunk_index": 1, "score": 0.1, "vector_score": 0.9, "source": "x"},
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[d1, d2]), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": "t",
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [doc_id],
            "top_k": 2,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    citations = out.get("citations") or []
    assert [c.get("chunk_id") for c in citations] == ["b", "a"]
    assert citations[0].get("reranker_provider") == "ltr"
    assert citations[0].get("rerank_score") is not None

