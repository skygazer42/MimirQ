from __future__ import annotations


def test_build_simhash_review_candidates_groups_near_duplicates_and_recommends_keep() -> None:
    from app.rag.tools.pre_poc_scanner.simhash_similarity import build_simhash_review_candidates

    out = build_simhash_review_candidates(
        [
            {
                "path": "/tmp/a.txt",
                "text": "North region revenue increased steadily in Q3.",
                "size_bytes": 100,
                "mtime": 1,
            },
            {
                "path": "/tmp/b.txt",
                "text": "North region revenue increased steadily in Q3!",
                "size_bytes": 120,
                "mtime": 2,
            },
            {
                "path": "/tmp/c.txt",
                "text": "Completely different content about supplier onboarding.",
                "size_bytes": 80,
                "mtime": 3,
            },
        ],
        hamming_threshold=5,
    )

    assert out["schema"] == "mimirq.pre_poc.simhash_review.v1"
    assert out["summary"]["clusters"] == 1
    assert out["summary"]["affected_files"] == 2
    cluster = out["clusters"][0]
    assert cluster["keep_candidate"] == "/tmp/b.txt"
    assert cluster["members"] == ["/tmp/b.txt", "/tmp/a.txt"]
    assert cluster["review_candidates"] == ["/tmp/a.txt"]


def test_collect_sensitive_review_samples_masks_context_and_separates_pii_and_secrets() -> None:
    from app.rag.tools.pre_poc_scanner.sensitive_info import collect_sensitive_review_samples

    text = (
        "Contact alice@example.com for access. "
        "Temporary token: sk-1234567890ABCDEF1234567890ABCDEF."
    )

    out = collect_sensitive_review_samples(text, pii_context_chars=20, secrets_context_chars=20)

    assert out["schema"] == "mimirq.pre_poc.sensitive_review.v1"
    assert out["pii_hits_total"]["email"] == 1
    assert out["secrets_hits_total"]["openai_key"] == 1

    pii_sample = next(item for item in out["samples"] if item["category"] == "pii")
    sec_sample = next(item for item in out["samples"] if item["category"] == "secret")

    assert pii_sample["kind"] == "email"
    assert sec_sample["kind"] == "openai_key"
    assert "alice@example.com" not in pii_sample["context"]
    assert "sk-1234567890ABCDEF1234567890ABCDEF" not in sec_sample["context"]
