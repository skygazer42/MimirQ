from __future__ import annotations

from app.parsing.enrich.table_canonical import extract_markdown_table
from app.parsing.enrich.table_renderers import render_table_csv, render_table_html, render_table_markdown


def test_extract_markdown_table_builds_cell_level_table_extraction() -> None:
    extraction = extract_markdown_table(
        "\n".join(
            [
                "Table 1@@1\t10\t100\t100\t180##",
                "| Name | Value |",
                "| --- | --- |",
                "| alpha | 1 |",
                "| beta | 2 |",
            ]
        ),
        page=1,
        bbox={"x0": 10, "x1": 100, "y0": 100, "y1": 180},
        source_element_id="media:0",
    )

    assert extraction is not None
    assert extraction.columns == ["Name", "Value"]
    assert extraction.row_count == 2
    assert extraction.col_count == 2
    assert extraction.header_rows == 1
    assert extraction.cells[0].is_header is True
    assert extraction.cells[2].text == "alpha"
    assert extraction.to_metadata()["source_page"] == 1
    assert extraction.to_metadata()["source_bbox"] == {"x0": 10, "x1": 100, "y0": 100, "y1": 180}


def test_table_renderers_emit_markdown_html_and_csv() -> None:
    extraction = extract_markdown_table(
        "\n".join(["| Name | Value |", "| --- | --- |", "| alpha | 1 |", "| beta | 2 |"]),
        page=1,
        source_element_id="media:0",
    )
    assert extraction is not None

    assert render_table_markdown(extraction).splitlines() == [
        "| Name | Value |",
        "| --- | --- |",
        "| alpha | 1 |",
        "| beta | 2 |",
    ]
    assert render_table_csv(extraction).splitlines() == ["Name,Value", "alpha,1", "beta,2"]
    html = render_table_html(extraction)
    assert "<table>" in html
    assert "<th>Name</th>" in html
    assert "<td>beta</td>" in html
