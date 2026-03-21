from __future__ import annotations

from pathlib import Path


def test_local_parse_cache_round_trip_and_expiry(tmp_path: Path) -> None:
    from app.parsing.processors.parse_cache import (
        LocalParseCacheStore,
        ParseCacheEntry,
        build_parse_cache_key,
    )

    store = LocalParseCacheStore(root=tmp_path)
    key = build_parse_cache_key(
        file_sha256="a" * 64,
        parser_backend="auto",
        config_hash="cfg-1",
    )

    store.set(
        key,
        ParseCacheEntry(
            created_at_epoch=1_000.0,
            file_sha256="a" * 64,
            parser_backend="auto",
            resolved_backend="docling",
            resolved_chunk_strategy="langchain_recursive",
            documents=[{"page_content": "hello", "metadata": {"page": 1}}],
            chunks=None,
        ),
    )

    hit, age_ms = store.get(key, ttl_sec=60, now_epoch=1_030.0)
    expired, expired_age_ms = store.get(key, ttl_sec=10, now_epoch=1_030.0)

    assert hit is not None
    assert hit.resolved_backend == "docling"
    assert age_ms == 30_000
    assert expired is None
    assert expired_age_ms is None
