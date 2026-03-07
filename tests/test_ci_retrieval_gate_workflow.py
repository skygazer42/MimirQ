from __future__ import annotations

from pathlib import Path


def test_ci_retrieval_gate_uses_bounded_hybrid_runtime_configuration() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'ENABLE_RERANKER: "true"' in text
    assert 'BM25_INDEX_ENABLED: "true"' in text
    assert 'LLM_MOCK_ENABLED: "true"' in text
    assert "--retrieval-mode hybrid \\" in text
    assert "--retrieval-mode keyword \\" not in text
