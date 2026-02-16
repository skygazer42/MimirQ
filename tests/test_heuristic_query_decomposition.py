from app.rag.core.text import heuristic_decompose_query


def test_heuristic_decompose_query_splits_on_punct_and_conjunctions():
    q = "Explain rate limits, and list retry headers; also show examples."
    out = heuristic_decompose_query(q, max_subquestions=3)
    assert out == [
        "Explain rate limits",
        "list retry headers",
        "show examples",
    ]


def test_heuristic_decompose_query_filters_tiny_fragments():
    assert heuristic_decompose_query("A and B", max_subquestions=3) == []


def test_heuristic_decompose_query_is_deterministic():
    q = "请解释证据门禁，并且说明 span 引用，以及如何做 query 分解？"
    a = heuristic_decompose_query(q, max_subquestions=3)
    b = heuristic_decompose_query(q, max_subquestions=3)
    assert a == b
    assert len(a) <= 3
    assert any("span" in s for s in a)

