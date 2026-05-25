from __future__ import annotations

from app.rag.retriever import HybridRetriever


def test_weight_rerank_promotes_exact_title_phrase_over_generic_token_overlap() -> None:
    retriever = HybridRetriever()

    docs = [
        {
            "document_id": "bert",
            "chunk_id": "bert-1",
            "content": (
                "BERT introduces bidirectional language model representations with deep contextualized "
                "pretraining for many natural language tasks."
            ),
            "score": 0.82,
        },
        {
            "document_id": "elmo",
            "chunk_id": "elmo-1",
            "content": (
                "Deep contextualized word representations are introduced from bidirectional language models "
                "and used as ELMo features."
            ),
            "score": 0.45,
        },
    ]

    out = retriever._weight_rerank(
        "Which paper introduces deep contextualized word representations from bidirectional language models?",
        docs,
        vector_weight=0.6,
        keyword_weight=0.4,
    )

    assert out[0]["document_id"] == "elmo"
    assert out[0]["exact_phrase_score"] > out[1]["exact_phrase_score"]
