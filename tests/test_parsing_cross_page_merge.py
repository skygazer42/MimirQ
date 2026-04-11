from __future__ import annotations

from app.parsing.processors.cross_page_merge import merge_cross_page_markdown_pages


def test_merge_cross_page_tables_continuation_without_header() -> None:
    prev = "\n".join(
        [
            "Intro",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "",
        ]
    )
    nxt = "\n".join(
        [
            "| 3 | 4 |",
            "| 5 | 6 |",
            "Tail",
            "",
        ]
    )

    merged, stats = merge_cross_page_markdown_pages([prev, nxt])
    assert stats["tables_merged"] == 1
    assert "| 5 | 6 |" in merged[0]
    assert merged[1].lstrip().startswith("Tail")


def test_merge_cross_page_tables_drops_repeated_header() -> None:
    prev = "\n".join(
        [
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "",
        ]
    )
    nxt = "\n".join(
        [
            "| A | B |",
            "| --- | --- |",
            "| 3 | 4 |",
            "Tail",
            "",
        ]
    )

    merged, stats = merge_cross_page_markdown_pages([prev, nxt])
    assert stats["tables_merged"] == 1
    # Header should only appear once in the merged first page.
    assert merged[0].count("| A | B |") == 1
    assert "| 3 | 4 |" in merged[0]
    assert merged[1].lstrip().startswith("Tail")


def test_merge_cross_page_ordered_list_continuation() -> None:
    prev = "\n".join(
        [
            "Intro",
            "1. a",
            "2. b",
            "",
        ]
    )
    nxt = "\n".join(
        [
            "3. c",
            "4. d",
            "Tail",
            "",
        ]
    )
    merged, stats = merge_cross_page_markdown_pages([prev, nxt])
    assert stats["lists_merged"] == 1
    assert "4. d" in merged[0]
    assert merged[1].lstrip().startswith("Tail")


def test_merge_cross_page_table_mismatch_does_not_merge() -> None:
    prev = "\n".join(
        [
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "",
        ]
    )
    nxt = "\n".join(
        [
            "| A | B | C |",
            "| --- | --- | --- |",
            "| 3 | 4 | 5 |",
            "",
        ]
    )

    merged, stats = merge_cross_page_markdown_pages([prev, nxt])
    assert stats["tables_merged"] == 0
    assert merged[1].lstrip().startswith("| A | B | C |")


def test_merge_cross_page_tables_skips_continuation_hint_before_repeated_header() -> None:
    prev = "\n".join(
        [
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "",
        ]
    )
    nxt = "\n".join(
        [
            "Table 1 (continued)",
            "| A | B |",
            "| --- | --- |",
            "| 3 | 4 |",
            "Tail",
            "",
        ]
    )

    merged, stats = merge_cross_page_markdown_pages([prev, nxt])
    assert stats["tables_merged"] == 1
    assert merged[0].count("| A | B |") == 1
    assert "Table 1 (continued)" not in merged[0]
    assert "| 3 | 4 |" in merged[0]
    assert merged[1].lstrip().startswith("Tail")
