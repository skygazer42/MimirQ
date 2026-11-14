import pytest

from app.rag.agents.multi_agent import MultiAgentRAGRunner, _SubAgentResult


@pytest.mark.parametrize(
    "extra_a,extra_b",
    [
        ({"page_number": 0}, {"page_number": None}),
        ({"source": "a|b", "snippet": "c"}, {"source": "a", "snippet": "b|c"}),
    ],
)
def test_multi_agent_collection_keeps_distinct_citation_identity_values(extra_a, extra_b):
    citations = [
        {"document_id": "doc-1", "chunk_id": "chunk-1", **extra_a},
        {"document_id": "doc-1", "chunk_id": "chunk-1", **extra_b},
    ]
    runner = MultiAgentRAGRunner.__new__(MultiAgentRAGRunner)
    result = _SubAgentResult(index=1, query="query", elapsed_sec=0.0, result={"citations": citations})
    _, collected, _, _ = runner._collect_retrieval_outputs(results=[result], retrieval_mode="hybrid", question="query")
    assert collected == citations
