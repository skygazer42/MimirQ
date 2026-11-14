"""Compatibility exports for the canonical evidence post-rerank cache owner."""

from app.rag.rerank_result_cache import (
    build_evidence_post_rerank_cache_key,
    clear_evidence_post_rerank_cache,
    clear_evidence_post_rerank_cache_for_tests,
    fingerprint_rerank_candidates,
    get_cached_evidence_post_rerank_result,
    get_evidence_post_rerank_cache_backend,
    set_cached_evidence_post_rerank_result,
)

__all__ = [
    "build_evidence_post_rerank_cache_key",
    "clear_evidence_post_rerank_cache",
    "clear_evidence_post_rerank_cache_for_tests",
    "fingerprint_rerank_candidates",
    "get_cached_evidence_post_rerank_result",
    "get_evidence_post_rerank_cache_backend",
    "set_cached_evidence_post_rerank_result",
]
