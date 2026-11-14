import pytest

from app.parsing.processors.parse_cache import LocalParseCacheStore, ParseCacheEntry


@pytest.mark.parametrize("strategy", [None, "", False, 0])
def test_local_cache_rejects_missing_chunk_strategy_facts(tmp_path, strategy) -> None:
    store = LocalParseCacheStore(root=tmp_path)
    entry = ParseCacheEntry(1, "sha", None, "integrated", strategy, None, [{"page_content": "cached", "metadata": {}}])
    store.set("key", entry)
    assert store.get("key", ttl_sec=0, now_epoch=1) == (None, None)


@pytest.mark.parametrize("strategy", ["auto", "integrated_basic"])
def test_local_cache_keeps_valid_chunks_only_provenance(tmp_path, strategy) -> None:
    store = LocalParseCacheStore(root=tmp_path)
    entry = ParseCacheEntry(1, "sha", None, "integrated", strategy, None, [{"page_content": "cached", "metadata": {}}])
    store.set("key", entry)
    actual, age = store.get("key", ttl_sec=0, now_epoch=1)
    assert actual == entry
    assert age == 0
