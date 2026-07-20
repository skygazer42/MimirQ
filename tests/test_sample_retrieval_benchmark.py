import json
from pathlib import Path

from scripts.run_sample_retrieval_benchmark import run_benchmark


def test_sample_benchmark_disables_external_reranking(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    from app.rag import retriever as retriever_module

    class _Retriever:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            assert kwargs["enable_reranker"] is False

        def upsert_bm25_documents(self, *_args, **_kwargs) -> None:  # noqa: ANN002,ANN003
            pass

        def _hybrid_search(self, **_kwargs) -> list[dict[str, object]]:  # noqa: ANN003
            return [{"chunk_id": "chunk-1"}]

    monkeypatch.setattr(retriever_module, "HybridRetriever", _Retriever)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "schema": "mimirq.sample_retrieval_fixture.v1",
                "documents": [{"chunk_id": "chunk-1", "text": "sample"}],
                "queries": [{"question": "sample?", "expected_chunk_ids": ["chunk-1"]}],
            }
        ),
        encoding="utf-8",
    )

    report = run_benchmark(
        fixture_path=fixture,
        output_path=tmp_path / "report.json",
        top_k=1,
        retrieval_mode="keyword",
    )

    assert report["summary"]["hit_at_k"] == 1.0
