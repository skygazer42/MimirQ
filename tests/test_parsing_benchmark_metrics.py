from __future__ import annotations

from app.parsing.quality.benchmark import (
    compute_parsing_proxy_metrics,
    extract_markdown_images,
    extract_pipe_tables,
    markdown_to_text,
    normalized_text_similarity,
    table_cell_f1,
)


def test_markdown_to_text_strips_images_and_links() -> None:
    md = "Hello ![img](a.png) [link](https://example.com) <b>bold</b>\n```py\nx=1\n```\n"
    text = markdown_to_text(md)
    assert "Hello" in text
    assert "img" not in text
    assert "https://example.com" not in text
    assert "bold" in text
    assert "x=1" not in text


def test_normalized_text_similarity_is_1_for_identical_text() -> None:
    md = "# Title\n\nHello world\n"
    assert normalized_text_similarity(md, md) == 1.0


def test_extract_markdown_images_counts_md_and_html() -> None:
    md = "![a](x.png)\n<img src=\"y.jpg\" alt=\"y\" />\n"
    imgs = extract_markdown_images(md)
    assert len(imgs) == 2


def test_extract_pipe_tables_and_cell_f1() -> None:
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    tables = extract_pipe_tables(md)
    assert len(tables) == 1
    assert table_cell_f1(tables, tables) == 1.0


def test_compute_parsing_proxy_metrics_smoke() -> None:
    gold = "| A | B |\n|---|---|\n| 1 | 2 |\n![img](a.png)\n"
    pred = "| A | B |\n|---|---|\n| 1 | 9 |\n![img](a.png)\n![img](b.png)\n"
    metrics = compute_parsing_proxy_metrics(parsed_markdown=pred, golden_markdown=gold)
    assert metrics["text_similarity"] > 0
    assert metrics["images_gold"] == 1
    assert metrics["images_pred"] == 2
    assert metrics["image_recall"] == 1.0
    assert metrics["table_grits_topology"] == 1.0
    assert 0.0 < metrics["table_grits_content"] < 1.0
    assert 0.0 < metrics["table_grits_f1"] < 1.0
