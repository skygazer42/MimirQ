from __future__ import annotations

from langchain_core.documents import Document

from app.rag.retriever import HybridRetriever


def _mk_result(*, doc_id: str, score: float, plugin_ref: str, product_line: str) -> dict:
    return {
        "chunk_id": f"{doc_id}:0",
        "content": f"chunk {doc_id}",
        "metadata": {
            "document_id": doc_id,
            "chunk_index": 0,
            "chunk_id": f"{doc_id}:0",
            "chunk_python_plugin": plugin_ref,
            "product_line": product_line,
        },
        "score": float(score),
    }


def test_native_retriever_fusion_applies_plugin_retrieval_policy(monkeypatch) -> None:  # noqa: ANN001
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    monkeypatch.setattr(
        HybridRetriever,
        "_retrieval_policy_for_plugin_ref",
        staticmethod(
            lambda ref: {
                "schema": "mimirq.retrieval_policy.v1",
                "boost_fields": [{"metadata": "product_line", "weight": 2.0, "match": "contains"}],
            }
            if ref == plugin_ref
            else {}
        ),
        raising=False,
    )
    retriever = HybridRetriever()
    retriever._last_channel_metrics = {}
    vector = [
        _mk_result(doc_id="doc-a", score=0.5, plugin_ref=plugin_ref, product_line="Beta Desk"),
        _mk_result(doc_id="doc-z", score=0.5, plugin_ref=plugin_ref, product_line="Alpha Desk"),
    ]

    out = retriever._merge_results(
        vector,
        bm25_results=[],
        lexical_results=[],
        sparse_results=[],
        query="Alpha Desk escalation path",
        fusion_strategy="linear",
    )

    assert [item["metadata"]["document_id"] for item in out[:2]] == ["doc-z", "doc-a"]
    assert out[0]["retrieval_policy_bonus"] > 0
    diagnostics = retriever._last_channel_metrics["retrieval_policy"]
    assert diagnostics["retrieval_policy_record_count"] == 2
    assert diagnostics["retrieval_policy_boost_field_record_count"] == 1
    assert diagnostics["score_adjusted_record_count"] == 1


def test_bm25_candidate_metadata_preserves_plugin_provenance_for_policy_lookup() -> None:
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    retriever = HybridRetriever()
    doc = Document(
        id="chunk-1",
        page_content="Demo record content",
        metadata={
            "tenant_id": "tenant-a",
            "dataset_id": "dataset-a",
            "document_id": "doc-a",
            "source": "demo-records.txt",
            "governance_python_plugin": "plugin:demo-service@1.0.0:governance",
            "chunk_python_plugin": plugin_ref,
            "kg_python_plugin": "plugin:demo-service@1.0.0:kg",
            "_indexed_metadata": {"product_line": "Alpha Desk"},
        },
    )

    result = retriever._bm25_result_from_doc(doc=doc, raw_score=1.0, final_score=1.0, question_channel_score=0.0)
    meta = result["metadata"]

    assert meta["chunk_python_plugin"] == plugin_ref
    assert meta["governance_python_plugin"] == "plugin:demo-service@1.0.0:governance"
    assert meta["kg_python_plugin"] == "plugin:demo-service@1.0.0:kg"
