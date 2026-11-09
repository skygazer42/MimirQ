import asyncio
from types import SimpleNamespace

import pytest

from app.services import chat_cache_runtime
from app.services.chunking_stats_utils import (
    compute_chunking_stats_from_texts,
    compute_chunking_stats_from_texts_tokens,
)


def test_cache_hit_requires_the_content_written_by_the_cache_producer(monkeypatch):
    monkeypatch.setattr(chat_cache_runtime, "prepare_chat_cache_lookup", lambda **kwargs: (True, "cache-key", None))

    async def get_payload(key):
        assert key == "cache-key"
        return {"metrics": {}}

    monkeypatch.setattr(chat_cache_runtime, "get_cached_chat_response_async", get_payload)
    with pytest.raises(KeyError, match="content"):
        asyncio.run(chat_cache_runtime.prepare_non_streaming_chat_cache_state(options=SimpleNamespace()))


def test_cache_store_does_not_silently_ignore_invalid_required_content(monkeypatch):
    def store_payload(*args):
        pytest.fail("Invalid content must not reach cache IO")

    monkeypatch.setattr(chat_cache_runtime, "set_cached_chat_response", store_payload)
    with pytest.raises(AttributeError):
        chat_cache_runtime.store_chat_response_cache_if_needed(
            cache_eligible=True,
            cache_hit=False,
            cache_key="cache-key",
            content=None,
            citations=[],
            metrics={},
            structured_data=None,
        )


@pytest.mark.parametrize("compute", [compute_chunking_stats_from_texts, compute_chunking_stats_from_texts_tokens])
def test_chunk_statistics_reject_missing_required_chunk_text(compute):
    with pytest.raises(AttributeError):
        compute([None])


@pytest.mark.parametrize("compute", [compute_chunking_stats_from_texts, compute_chunking_stats_from_texts_tokens])
def test_chunk_statistics_keep_valid_empty_and_duplicate_chunk_behavior(compute):
    result = compute(["", "abc", "abc"])
    assert result["count"] == 2
    assert result["duplicate_count"] == 1
