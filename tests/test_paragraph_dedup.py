from app.rag.preprocessing.paragraph_dedup import drop_duplicate_paragraphs


def test_drop_duplicate_paragraphs_drops_repeated_blocks():
    text = "\n\n".join(
        [
            "Header boilerplate",
            "Header boilerplate",
            "Header boilerplate",
            "Unique paragraph",
        ]
    )
    res = drop_duplicate_paragraphs(text, min_occurrences=3, min_paragraph_chars=5)
    assert res.changed is True
    assert "Header boilerplate" not in res.text
    assert "Unique paragraph" in res.text
    assert res.paragraphs_dropped == 3


def test_drop_duplicate_paragraphs_keeps_headings():
    text = "\n\n".join(
        [
            "# Title",
            "# Title",
            "# Title",
            "Body",
        ]
    )
    res = drop_duplicate_paragraphs(text, min_occurrences=3, min_paragraph_chars=1)
    assert "# Title" in res.text
    assert "Body" in res.text
    assert res.paragraphs_dropped == 0

