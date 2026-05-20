from __future__ import annotations

from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.strategy_matrix import run_chunk_strategy_matrix, validate_strategy_fixture_mapping


def test_chunk_strategy_matrix_fixture_mapping_covers_all_strategies() -> None:
    validate_strategy_fixture_mapping()


def test_chunk_strategy_matrix_all_supported_strategies_produce_chunks_or_are_explicitly_unavailable() -> None:
    results = run_chunk_strategy_matrix()
    expected = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    actual = {str(row.get("strategy") or "") for row in results}
    assert actual == expected

    hard_failures = [row for row in results if row.get("status") not in {"passed", "unavailable"}]
    assert not hard_failures

    allowed_unavailable = set()
    try:
        import llama_index.core  # noqa: F401
    except Exception:
        allowed_unavailable.update({"llama_index", "llama_index_hierarchical"})

    unexpected_unavailable = [row for row in results if row.get("status") == "unavailable" and row.get("strategy") not in allowed_unavailable]
    assert not unexpected_unavailable
