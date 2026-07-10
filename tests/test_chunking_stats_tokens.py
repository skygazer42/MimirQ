

def test_compute_chunking_stats_from_texts_tokens_counts_and_histogram() -> None:
    from app.services.chunking_stats_utils import compute_chunking_stats_from_texts_tokens

    stats = compute_chunking_stats_from_texts_tokens(
        [
            "hello world",
            "hello world",  # duplicate
            "a" * 1000,  # ~250 tokens (ASCII heuristic)
        ]
    )

    assert isinstance(stats, dict)
    assert stats.get("unit") == "tokens"
    assert stats.get("count") == 3
    assert stats.get("duplicate_count") == 1
    assert stats.get("short_threshold") == 40
    assert stats.get("short_count") == 2

    hist = {b.get("label"): int(b.get("count") or 0) for b in (stats.get("histogram") or []) if isinstance(b, dict)}
    assert hist.get("0-50") == 2
    assert hist.get("200-400") == 1

