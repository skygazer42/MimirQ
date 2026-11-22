from app.rag.ingestion.chunking.capabilities import EXPERIMENTAL_STRATEGIES
from app.rag.ingestion.chunking.factory import chunker_factory
from app.rag.ingestion.chunking.recommendations import decorate_chunk_strategy_note


def test_chunking_recommendations_label_mainstream_and_specialized_strategies() -> None:
    mainstream = decorate_chunk_strategy_note("langchain_recursive", "Recursive splitter.")
    specialized = decorate_chunk_strategy_note("docker_compose", "Compose service-aware chunking.")
    experimental = decorate_chunk_strategy_note("proposition", "Proposition splitter.")
    optional = decorate_chunk_strategy_note("llama_index", "Requires LLAMA_INDEX_ENABLED=true.")

    assert mainstream and mainstream.startswith("[Mainstream RAG recommended]")
    assert specialized and specialized.startswith("[Specialized document strategy]")
    assert experimental and experimental.startswith("[Experimental or corpus-specific]")
    assert optional and optional.startswith("[Optional dependency]")
    assert "raptor" not in EXPERIMENTAL_STRATEGIES
    assert "raptor" not in chunker_factory.SUPPORTED_STRATEGIES
