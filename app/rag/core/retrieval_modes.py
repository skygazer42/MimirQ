"""Dependency-light retrieval mode normalization shared by routing and text helpers."""

_VALID_RETRIEVAL_MODES = {"hybrid", "vector", "keyword", "mmr", "auto"}
_RETRIEVAL_MODE_ALIASES = {
    "fulltext": "keyword",
    "bm25": "keyword",
    "sparse": "keyword",
    "lexical": "keyword",
    "dense": "vector",
    "semantic": "vector",
}


def normalize_retrieval_mode(mode: str | None) -> str:
    """Normalize supported modes and legacy aliases, defaulting to hybrid."""
    raw = (mode or "").strip().lower()
    if not raw:
        return "hybrid"
    mapped = _RETRIEVAL_MODE_ALIASES.get(raw, raw)
    if mapped in _VALID_RETRIEVAL_MODES:
        return mapped
    return "hybrid"


__all__ = ["normalize_retrieval_mode"]
