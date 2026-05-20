from __future__ import annotations

from app.rag.chunking.recommendations import decorate_chunk_strategy_note


def test_chunking_recommendations_label_mainstream_and_specialized_strategies() -> None:
    mainstream = decorate_chunk_strategy_note("langchain_recursive", "Recursive splitter.")
    specialized = decorate_chunk_strategy_note("docker_compose", "Compose service-aware chunking.")
    experimental = decorate_chunk_strategy_note("raptor", "Hierarchical chunk scaffold.")
    optional = decorate_chunk_strategy_note("llama_index", "Requires LLAMA_INDEX_ENABLED=true.")

    assert mainstream and mainstream.startswith("[Mainstream RAG recommended]")
    assert specialized and specialized.startswith("[Specialized document strategy]")
    assert experimental and experimental.startswith("[Experimental or corpus-specific]")
    assert optional and optional.startswith("[Optional dependency]")
