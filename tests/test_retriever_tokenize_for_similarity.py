from app.rag.retriever import HybridRetriever


def test_tokenize_for_similarity_filters_stopwords():
    tokens = HybridRetriever._tokenize_for_similarity("the quick brown fox")
    assert "the" not in tokens
    assert "quick" in tokens
    assert "brown" in tokens
    assert "fox" in tokens

