from app.rag.evaluation.kg_hardcase_deterministic import generate_hardcases_deterministic


def test_deterministic_hardcases_split_2_2() -> None:
    out = generate_hardcases_deterministic(
        question="How does Retrieval-Augmented Generation work?",
        alias_pairs=[("Retrieval-Augmented Generation", "RAG"), ("Large Language Model", "LLM")],
        skills=["Build a vector index", "Chunk a document"],
        tags=["milvus", "embedding"],
        max_items=4,
    )
    assert len(out) == 4
    # Alias pressure first.
    assert "RAG" in out[0].question
    assert out[0].kind == "knowledge_pressure"
    # Skills second.
    assert out[2].question.startswith("How to ")


def test_deterministic_hardcases_dedupe_and_cap() -> None:
    out = generate_hardcases_deterministic(
        question="What is RAG?",
        alias_pairs=[("RAG", "Retrieval-Augmented Generation"), ("RAG", "Retrieval-Augmented Generation")],
        skills=["Build a vector index", "Chunk a document", "Tune BM25"],
        tags=[],
        max_items=3,
    )
    assert len(out) == 3
    qs = [h.question for h in out]
    assert len({q.casefold() for q in qs}) == 3


def test_deterministic_hardcases_spillover_when_alias_missing() -> None:
    out = generate_hardcases_deterministic(
        question="How to build RAG?",
        alias_pairs=[],
        skills=["Build a vector index", "Chunk a document", "Tune BM25"],
        tags=["milvus", "embedding", "bm25"],
        max_items=4,
    )
    assert len(out) == 4
    assert all(h.kind == "knowledge_pressure" for h in out)
