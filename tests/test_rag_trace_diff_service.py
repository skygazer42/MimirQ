from app.rag.trace_schema import RagTrace, RagTraceCitation, RagTraceRerank, RagTraceRetrieval


def test_diff_rag_traces_reports_config_and_citation_deltas() -> None:
    from app.services.rag_trace_diff_service import RAG_TRACE_DIFF_SCHEMA_V1, diff_rag_traces

    a = RagTrace(
        ts_ms=1,
        request_id="req_a",
        conversation_id="conv",
        retrieval=RagTraceRetrieval(mode="vector", retrieval_config_hash="cfg_a", top_k=10, elapsed_sec=0.5),
        rerank=RagTraceRerank(enabled=False, provider=None, top_n=None, elapsed_sec=None, model_used=None),
        citations=[
            RagTraceCitation(document_id="d1", chunk_id="c1", hit_type="vector", retrieval_role="main"),
            RagTraceCitation(document_id="d2", chunk_id="c2", hit_type="keyword", retrieval_role="main"),
        ],
        citations_count=2,
        steps=[],
    )

    b = RagTrace(
        ts_ms=2,
        request_id="req_b",
        conversation_id="conv",
        retrieval=RagTraceRetrieval(mode="hybrid", retrieval_config_hash="cfg_b", top_k=20, elapsed_sec=0.8),
        rerank=RagTraceRerank(enabled=True, provider="ltr", top_n=30, elapsed_sec=0.2, model_used="xgb:v1"),
        citations=[
            RagTraceCitation(document_id="d1", chunk_id="c1", hit_type="vector", retrieval_role="main"),
            RagTraceCitation(document_id="d2", chunk_id="c2", hit_type="keyword", retrieval_role="main"),
            RagTraceCitation(document_id="d3", chunk_id="c3", hit_type="hybrid", retrieval_role="kg"),
        ],
        citations_count=3,
        steps=[],
    )

    diff = diff_rag_traces(a, b)

    assert diff.get("schema") == RAG_TRACE_DIFF_SCHEMA_V1
    assert diff.get("request_id_a") == "req_a"
    assert diff.get("request_id_b") == "req_b"
    assert diff.get("retrieval_config_hash_a") == "cfg_a"
    assert diff.get("retrieval_config_hash_b") == "cfg_b"
    assert diff.get("delta", {}).get("citations_count") == 1
    assert diff.get("fields", {}).get("retrieval.mode", {}).get("a") == "vector"
    assert diff.get("fields", {}).get("retrieval.mode", {}).get("b") == "hybrid"

