from __future__ import annotations

from pathlib import Path

from app.parsing.parsers.image_parser import ImageParser


def test_image_parser_emits_markdown_reference(tmp_path: Path) -> None:
    img = tmp_path / "hello world.png"
    img.write_bytes(b"not-a-real-png")

    docs = ImageParser().parse(img)
    assert len(docs) == 1
    doc = docs[0]
    assert "![](" in (doc.page_content or "")
    # Space should be percent-encoded.
    assert "hello%20world.png" in (doc.page_content or "")
    meta = doc.metadata or {}
    assert meta.get("parser_backend") == "image"
    assert meta.get("asset_base_dir") == str(tmp_path.resolve(strict=False))


def test_image_parser_emits_table_document_for_borderless_table_fixture() -> None:
    img = Path("tests/fixtures/parsing_golden_broader/borderless_table_scan/input/sample.png")

    docs = ImageParser().parse(img)

    assert len(docs) == 1
    doc = docs[0]
    meta = doc.metadata or {}
    assert meta.get("doc_type_kwd") == "table"
    assert meta.get("content_type") == "table"
    assert "| Item | Qty | Warehouse |" in (doc.page_content or "")
    assert "| Paper | 220 | HZ-A |" in (doc.page_content or "")
