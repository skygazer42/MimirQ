from pathlib import Path
import tempfile

from app.rag.preprocessing.near_dedup import (
    add_simhashes,
    find_near_duplicate,
    load_near_dedup_index,
    save_near_dedup_index,
    with_near_dedup_index,
)
from app.rag.preprocessing.simhash import hamming_distance64, simhash64, simhash64_hex


def test_simhash64_and_hamming_distance_are_stable():
    a = simhash64("hello world")
    b = simhash64("hello world")
    c = simhash64("completely different text")

    assert a == b
    assert hamming_distance64(a, b) == 0
    assert hamming_distance64(a, c) >= 0
    assert len(simhash64_hex(a)) == 16


def test_near_dedup_index_roundtrip_and_match():
    sh = simhash64_hex(simhash64("hello world"))
    buckets: dict[str, list[str]] = {}
    add_simhashes(buckets=buckets, simhashes=[sh], max_bucket_size=10)

    match = find_near_duplicate(buckets=buckets, simhash64_hex=sh, hamming_threshold=0, max_bucket_size=10)
    assert match is not None
    assert match.simhash64 == sh
    assert match.distance == 0

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "dedup.json"
        save_near_dedup_index(path, buckets)
        loaded = load_near_dedup_index(path)
        match2 = find_near_duplicate(buckets=loaded, simhash64_hex=sh, hamming_threshold=0, max_bucket_size=10)
        assert match2 is not None
        assert match2.simhash64 == sh


def test_with_near_dedup_index_updates_file():
    sh = simhash64_hex(simhash64("hello world"))
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "dedup.json"

        def _update(buckets: dict[str, list[str]]):  # noqa: ANN001
            add_simhashes(buckets=buckets, simhashes=[sh], max_bucket_size=10)
            return buckets

        with_near_dedup_index(path=path, fn=_update)
        loaded = load_near_dedup_index(path)
        assert loaded

