from app.rag.preprocessing.references import trim_references_section


def test_trim_references_section_trims_tail_when_citation_like():
    text = "\n".join(
        [
            "Intro",
            "Body",
            "",
            "# References",
            "[1] Paper one",
            "[2] Paper two",
            "[3] Paper three",
            "[4] Paper four",
            "[5] Paper five",
            "[6] Paper six",
            "[7] Paper seven",
            "[8] Paper eight",
        ]
    )
    res = trim_references_section(text, min_position_ratio=0.2, min_lines_after=3, citation_like_ratio=0.2)
    assert res.changed is True
    assert "References" not in res.text
    assert "Intro" in res.text


def test_trim_references_section_keeps_when_not_citation_like():
    text = "\n".join(
        [
            "Intro",
            "",
            "## References",
            "This is not a bibliography list.",
            "More narrative text.",
        ]
    )
    res = trim_references_section(text, min_position_ratio=0.2, min_lines_after=1, citation_like_ratio=0.9)
    assert res.changed is False
    assert "This is not a bibliography list." in res.text

