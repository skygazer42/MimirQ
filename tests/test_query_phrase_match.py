from __future__ import annotations


def test_query_phrase_match_normalizes_filename_separators() -> None:
    from app.rag.retrieval.query_phrase_match import query_phrase_match

    out = query_phrase_match(
        "Which neural machine translation paper jointly learns to align and translate?",
        "neural-machine-translation-align-translate_1409.0473.pdf",
    )

    assert out["score"] > 0.8
