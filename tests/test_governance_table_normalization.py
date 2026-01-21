from app.rag.preprocessing.tables import normalize_markdown_tables


def test_normalize_markdown_tables_aligns_rows_and_separator():
    text = "\n".join(
        [
            "| a|b |",
            "|---| ---:|",
            "| 1|2|",
        ]
    )
    res = normalize_markdown_tables(text)

    assert res.tables == 1
    assert res.changed is True
    assert res.text.splitlines() == [
        "| a | b |",
        "| --- | ---: |",
        "| 1 | 2 |",
    ]


def test_normalize_markdown_tables_skips_code_fences():
    text = "\n".join(
        [
            "```md",
            "| a|b |",
            "|---|---|",
            "```",
            "| a|b |",
            "|---|---|",
        ]
    )
    res = normalize_markdown_tables(text)

    lines = res.text.splitlines()
    # In code fence: unchanged.
    assert lines[1] == "| a|b |"
    assert lines[2] == "|---|---|"
    # Outside code fence: normalized.
    assert lines[4] == "| a | b |"
    assert lines[5] == "| --- | --- |"

