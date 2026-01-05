from __future__ import annotations

from app.api.v1.documents import _compute_pipeline_hash


def test_pipeline_hash_is_stable_and_short():
    meta = {
        "parser_backend": "auto",
        "parser_backend_requested": "auto",
        "chunk_strategy": "langchain_recursive",
        "chunk_strategy_requested": "langchain_recursive",
        "pipeline": {"governance_enabled": True, "chunk_size": 1000},
    }
    h1 = _compute_pipeline_hash(dict(meta))
    h2 = _compute_pipeline_hash(dict(meta))
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 16


def test_pipeline_hash_changes_with_pipeline_options():
    meta1 = {
        "parser_backend": "auto",
        "parser_backend_requested": "auto",
        "chunk_strategy": "langchain_recursive",
        "chunk_strategy_requested": "langchain_recursive",
        "pipeline": {"governance_enabled": True, "chunk_size": 1000},
    }
    meta2 = {
        **meta1,
        "pipeline": {"governance_enabled": False, "chunk_size": 1000},
    }
    assert _compute_pipeline_hash(meta1) != _compute_pipeline_hash(meta2)


