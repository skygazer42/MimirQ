from __future__ import annotations

from langchain_core.documents import Document


def test_agentic_chunker_emits_offline_judge_metadata() -> None:
    from app.rag.chunking.strategies.agentic_chunker import AgenticChunker

    chunker = AgenticChunker(chunk_size=90, chunk_overlap=0)
    out = chunker.split_documents(
        [
            Document(
                page_content=(
                    "Problem statement: the billing export misses tax lines.\n"
                    "1. Open the finance console.\n"
                    "2. Rebuild the ledger snapshot.\n"
                    "3. Verify the CSV totals.\n"
                    "Root cause summary: an upstream mapper drops the tax column."
                ),
                metadata={"source": "runbook.md"},
            )
        ]
    )

    assert out
    assert all((doc.metadata or {}).get("chunk_strategy") == "agentic_chunker" for doc in out)
    assert all((doc.metadata or {}).get("agentic_chunker_mode") == "offline_batch" for doc in out)
    assert all((doc.metadata or {}).get("agentic_chunker_judge") == "heuristic" for doc in out)
    assert all(isinstance((doc.metadata or {}).get("agentic_chunker_signals"), list) for doc in out)
    assert any("list_boundary" in ((doc.metadata or {}).get("agentic_chunker_signals") or []) for doc in out)


def test_chunker_factory_supports_agentic_chunker_strategy() -> None:
    from app.rag.chunking.factory import chunker_factory
    from app.rag.chunking.strategies.agentic_chunker import AgenticChunker

    chunker = chunker_factory.get_chunker("agentic_chunker", chunk_size=100, chunk_overlap=0)
    assert isinstance(chunker, AgenticChunker)
