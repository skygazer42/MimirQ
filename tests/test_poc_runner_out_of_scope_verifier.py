from __future__ import annotations

from app.rag.evaluation.poc_runner.out_of_scope_verifier import verify_out_of_scope_query


def test_verify_out_of_scope_query_runs_all_three_stages_and_returns_out_of_scope() -> None:
    seen_queries: list[str] = []

    def _keyword_search(query: str):  # noqa: ANN001
        seen_queries.append(query)
        return []

    def _vector_search(query: str):  # noqa: ANN001
        if "假设文档" in query:
            return [{"score": 0.21}]
        return [{"score": 0.18}]

    result = verify_out_of_scope_query(
        query="X9 新型号怎么接线？",
        glossary={"接线": ["接线图"]},
        keyword_search=_keyword_search,
        vector_search=_vector_search,
        hyde_generate=lambda _query: "假设文档：X9 接线图与端子定义",
        vector_similarity_threshold=0.3,
        hyde_similarity_threshold=0.3,
    )

    assert result["l1_keyword_hit"] is False
    assert result["l2_top1_sim"] == 0.18
    assert result["l3_hyde_hit"] is False
    assert result["verdict"] == "out_of_scope"
    assert any("接线图" in item for item in seen_queries)


def test_verify_out_of_scope_query_can_skip_hyde_stage() -> None:
    result = verify_out_of_scope_query(
        query="485 怎么配置？",
        glossary={},
        keyword_search=lambda _query: [{"document_id": "doc-1"}],
        vector_search=lambda _query: [{"score": 0.72}],
        hyde_generate=lambda _query: "unused",
        vector_similarity_threshold=0.3,
        hyde_similarity_threshold=0.3,
        enable_hyde=False,
    )

    assert result["l1_keyword_hit"] is True
    assert result["l2_top1_sim"] == 0.72
    assert result["l3_hyde_hit"] is None
    assert result["verdict"] == "in_scope"
