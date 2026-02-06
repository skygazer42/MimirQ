from __future__ import annotations


def test_content_hash_multiset_diff_counts():
    from app.services.document_version_diff_service import content_hash_multiset_diff

    diff = content_hash_multiset_diff(
        from_hashes=["A", "B", "C"],
        to_hashes=["A", "B", "D", "D"],
    )

    assert diff.from_chunk_count == 3
    assert diff.to_chunk_count == 4
    assert diff.unchanged_chunks == 2
    assert diff.added_chunks == 2
    assert diff.removed_chunks == 1

