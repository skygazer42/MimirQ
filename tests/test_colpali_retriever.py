from __future__ import annotations

from uuid import uuid4


def test_search_colpali_retriever_applies_visual_document_filter(monkeypatch) -> None:  # noqa: ANN001
    from app.rag.retriever import HybridRetriever

    captured: dict[str, object] = {}

    def _fake_bm25(*, query, top_k, document_ids, tenant_id, metadata_filter=None):  # noqa: ANN001
        captured["metadata_filter"] = metadata_filter
        return [
            {
                "chunk_id": "c1",
                "content": "[visual-document](page-1.png)",
                "metadata": {"document_id": str(uuid4()), "chunk_id": "c1", "source": "page-1.png"},
                "score": 0.7,
            }
        ]

    r = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    monkeypatch.setattr(r, "_search_bm25", _fake_bm25, raising=True)

    out = r._search_colpali_retriever(
        query="show the login screenshot",
        top_k=3,
        document_ids=None,
        tenant_id=r.tenant_id,
        metadata_filter={"dataset_id": "ds-1"},
    )

    filt = captured.get("metadata_filter") or {}
    assert filt["$and"][0] == {"dataset_id": "ds-1"}
    visual = filt["$and"][1]["$or"]
    assert {"visual_parser": "colpali"} in visual
    assert {"content_type": "visual_document"} in visual
    assert out[0]["colpali_score"] == 0.7
    assert out[0]["hit_type"] == "colpali_retriever"


def test_hybrid_search_uses_colpali_channel_for_image_queries(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.retriever as retriever_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "COLPALI_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "app.rag.policy.modality_router.classify_query_modality",
        lambda _query: ("image", ["image_hint"]),
        raising=True,
    )

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            return []

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    r = retriever_mod.HybridRetriever(tenant_id=uuid4(), account_id="acct")
    monkeypatch.setattr(r, "_search_bm25", lambda **_k: [], raising=True)
    monkeypatch.setattr(r, "_search_lexical_db", lambda **_k: [], raising=False)
    monkeypatch.setattr(
        r,
        "_search_colpali_retriever",
        lambda **_k: [
            {
                "chunk_id": "c1",
                "content": "[visual-document](page-1.png)",
                "metadata": {"document_id": str(uuid4()), "chunk_id": "c1", "source": "page-1.png"},
                "score": 0.7,
                "colpali_score": 0.7,
                "lexical_score": 0.7,
                "hit_type": "colpali_retriever",
            }
        ],
        raising=True,
    )

    out = r._hybrid_search(
        query="show the login screenshot",
        top_k=3,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=r.tenant_id,
        retrieval_mode="hybrid",
        metadata_filter=None,
    )

    assert len(out) == 1
    assert out[0]["hit_type"] == "colpali_retriever"
    ch = r._last_channel_metrics or {}
    counts = ch.get("counts") or {}
    assert counts.get("colpali_candidates") == 1
    colpali = ch.get("colpali") or {}
    assert colpali.get("enabled") is True
    assert colpali.get("used") is True
