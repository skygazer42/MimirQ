from app.rag.tools.pre_poc_scanner.simhash_similarity import build_simhash_review_candidates


def test_simhash_review_candidates_groups_duplicates_and_picks_stable_keep_candidate() -> None:
    result = build_simhash_review_candidates(
        [
            {"path": "b.txt", "text": "same content", "size_bytes": 12, "mtime": 2},
            {"path": "a.txt", "text": "same content", "size_bytes": 12, "mtime": 2},
            {"path": "unique.txt", "text": "completely unrelated words"},
            {"path": "", "text": "ignored"},
        ],
        hamming_threshold=0,
    )

    assert result["summary"] == {
        "clusters": 1,
        "affected_files": 2,
        "pairs": 1,
        "threshold": 0,
    }
    assert result["clusters"][0]["members"] == ["a.txt", "b.txt"]
    assert result["clusters"][0]["keep_candidate"] == "a.txt"
    assert result["clusters"][0]["review_candidates"] == ["b.txt"]
    assert result["pairs"] == [{"a": "b.txt", "b": "a.txt", "distance": 0}]
